"""Experiment tracking — git-based with TSV logging."""

import os
import json
import subprocess
import time
import re
from datetime import datetime, timezone

from evaluator import (
    parse_evaluator_config,
    ScriptEvaluator,
    AgentEvaluator,
    HybridEvaluator,
    compute_hybrid_score,
)


class ExperimentTracker:
    def __init__(self, project_path: str):
        self.project_path = project_path
        self.ar_dir = os.path.join(project_path, ".autoresearch")
        self.results_file = os.path.join(self.ar_dir, "results.tsv")
        self.state_file = os.path.join(self.ar_dir, "state.json")
        self.evaluator_file = os.path.join(self.ar_dir, "evaluator.json")

    def _run_git(self, *args) -> tuple[int, str]:
        """Run git command in project dir."""
        result = subprocess.run(
            ["git"] + list(args),
            cwd=self.project_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode, (result.stdout + result.stderr).strip()

    def init_session(self, tag: str = None, description: str = "") -> dict:
        """Initialize an autoresearch session — create branch, baseline."""
        # Ensure git repo
        code, _ = self._run_git("rev-parse", "--git-dir")
        if code != 0:
            self._run_git("init")

        # Create .autoresearch dir
        os.makedirs(self.ar_dir, exist_ok=True)

        # Generate tag
        if not tag:
            tag = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        branch = f"autoresearch/{tag}"

        # Get current branch
        _, current = self._run_git("branch", "--show-current")

        # Create and checkout branch
        self._run_git("checkout", "-b", branch)

        # Init results.tsv
        if not os.path.exists(self.results_file):
            with open(self.results_file, "w") as f:
                f.write("experiment\tcommit\tscore\tmetrics\tstatus\tdescription\ttimestamp\n")

        # Save state
        state = {
            "tag": tag,
            "branch": branch,
            "base_branch": current,
            "started": datetime.now(timezone.utc).isoformat(),
            "description": description,
            "experiment_count": 0,
            "best_score": None,
            "last_good_commit": None,
        }
        with open(self.state_file, "w") as f:
            json.dump(state, f, indent=2)

        # Add .autoresearch to gitignore if needed
        gitignore = os.path.join(self.project_path, ".gitignore")
        ignore_line = ".autoresearch/"
        if os.path.exists(gitignore):
            with open(gitignore) as f:
                if ignore_line not in f.read():
                    with open(gitignore, "a") as f2:
                        f2.write(f"\n{ignore_line}\n")
        else:
            with open(gitignore, "w") as f:
                f.write(f"{ignore_line}\n")

        return state

    def load_state(self) -> dict | None:
        """Load current autoresearch state."""
        if not os.path.exists(self.state_file):
            return None
        with open(self.state_file) as f:
            return json.load(f)

    def save_state(self, state: dict):
        """Save state."""
        with open(self.state_file, "w") as f:
            json.dump(state, f, indent=2)

    def load_evaluator_config(self) -> dict:
        """Load evaluator config. Falls back to script type if only eval.sh exists."""
        if os.path.exists(self.evaluator_file):
            with open(self.evaluator_file) as f:
                return json.load(f)
        # Backwards compat: old sessions only have eval.sh
        if os.path.exists(os.path.join(self.ar_dir, "eval.sh")):
            return {"type": "script"}
        return {"type": "script"}

    def save_evaluator_config(self, config: dict):
        """Save evaluator config."""
        with open(self.evaluator_file, "w") as f:
            json.dump(config, f, indent=2)

    def run_eval(self) -> dict:
        """Run evaluation using the configured strategy."""
        config = self.load_evaluator_config()
        eval_type = config.get("type", "script")

        if eval_type == "script":
            return ScriptEvaluator(self.project_path, self.ar_dir).run()
        elif eval_type == "agent":
            return AgentEvaluator(self.project_path, config).prepare()
        elif eval_type == "hybrid":
            def save_pending_script_score(score):
                state = self.load_state()
                if state:
                    state["pending_script_score"] = score
                    self.save_state(state)
            return HybridEvaluator(
                self.project_path, self.ar_dir, config,
                save_state_fn=save_pending_script_score,
            ).run()
        else:
            return {"error": f"Unknown evaluator type: {eval_type}"}

    def submit_eval_score(self, score: float, metrics: dict = None,
                          assessment: str = None) -> dict:
        """Submit an agent-provided score. Handles hybrid weighting if applicable."""
        config = self.load_evaluator_config()
        state = self.load_state()
        final_metrics = metrics or {}

        if assessment:
            final_metrics["agent_assessment"] = assessment

        if config.get("type") == "hybrid":
            # Load pending script score from state
            script_score = state.get("pending_script_score")
            if script_score is not None:
                weights = config.get("weights", {"script": 0.6, "agent": 0.4})
                final_score = compute_hybrid_score(script_score, score, weights)
                final_metrics["script_score"] = script_score
                final_metrics["agent_score"] = score
                final_metrics["weights"] = weights
                # Clear pending
                state.pop("pending_script_score", None)
                self.save_state(state)
                return {
                    "score": final_score,
                    "script_score": script_score,
                    "agent_score": score,
                    "metrics": final_metrics,
                    "strategy": "hybrid",
                }
            else:
                # No pending script score — just use agent score
                return {
                    "score": score,
                    "metrics": final_metrics,
                    "strategy": "hybrid",
                    "warning": "No pending script score found, using agent score only.",
                }
        else:
            # Pure agent eval
            return {
                "score": score,
                "metrics": final_metrics,
                "strategy": "agent",
            }

    def log_experiment(self, description: str, score: float, metrics: dict,
                       status: str = "keep") -> dict:
        """Log experiment to results.tsv and update state."""
        state = self.load_state()
        if not state:
            return {"error": "No active session"}

        state["experiment_count"] += 1
        exp_num = state["experiment_count"]

        # Get current commit
        _, commit = self._run_git("rev-parse", "--short", "HEAD")

        # Write to TSV
        metrics_str = json.dumps(metrics) if metrics else "{}"
        timestamp = datetime.now(timezone.utc).isoformat()
        with open(self.results_file, "a") as f:
            f.write(f"{exp_num}\t{commit}\t{score}\t{metrics_str}\t{status}\t{description}\t{timestamp}\n")

        # Update best
        if status == "keep" and score is not None:
            if state["best_score"] is None or score > state["best_score"]:
                state["best_score"] = score
                state["last_good_commit"] = commit

        self.save_state(state)

        return {
            "experiment": exp_num,
            "commit": commit,
            "score": score,
            "status": status,
            "best_score": state["best_score"],
        }

    def keep_experiment(self, message: str) -> dict:
        """Git commit the current state as a kept experiment."""
        self._run_git("add", "-A")
        code, out = self._run_git("commit", "-m", f"[autoresearch] {message}")
        if code != 0:
            return {"error": f"Commit failed: {out}"}
        _, commit = self._run_git("rev-parse", "--short", "HEAD")
        return {"status": "committed", "commit": commit}

    def revert_experiment(self) -> dict:
        """Revert all changes back to last commit."""
        self._run_git("checkout", "--", ".")
        self._run_git("clean", "-fd")
        _, commit = self._run_git("rev-parse", "--short", "HEAD")
        return {"status": "reverted", "commit": commit}

    def get_history(self, limit: int = 50) -> list[dict]:
        """Read results.tsv and return experiments."""
        if not os.path.exists(self.results_file):
            return []

        results = []
        with open(self.results_file) as f:
            header = f.readline().strip().split("\t")
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= len(header):
                    row = dict(zip(header, parts))
                    results.append(row)

        return results[-limit:]

    def get_summary(self) -> dict:
        """Get session summary."""
        state = self.load_state()
        if not state:
            return {"error": "No active session"}

        history = self.get_history(1000)
        kept = [h for h in history if h.get("status") == "keep"]
        reverted = [h for h in history if h.get("status") == "revert"]
        crashed = [h for h in history if h.get("status") == "crash"]

        return {
            "tag": state["tag"],
            "branch": state["branch"],
            "started": state["started"],
            "total_experiments": len(history),
            "kept": len(kept),
            "reverted": len(reverted),
            "crashed": len(crashed),
            "best_score": state.get("best_score"),
            "last_good_commit": state.get("last_good_commit"),
        }

    def end_session(self) -> dict:
        """End session — return to base branch."""
        state = self.load_state()
        if not state:
            return {"error": "No active session"}

        summary = self.get_summary()
        base = state.get("base_branch", "main")
        self._run_git("checkout", base)

        return {
            "ended": True,
            "returned_to": base,
            **summary,
        }
