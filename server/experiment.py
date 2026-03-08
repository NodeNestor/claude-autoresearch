"""Experiment tracking — git-based with TSV logging."""

import os
import json
import subprocess
import time
import re
from datetime import datetime, timezone


class ExperimentTracker:
    def __init__(self, project_path: str):
        self.project_path = project_path
        self.ar_dir = os.path.join(project_path, ".autoresearch")
        self.results_file = os.path.join(self.ar_dir, "results.tsv")
        self.state_file = os.path.join(self.ar_dir, "state.json")

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

    def run_eval(self) -> dict:
        """Run the eval script and parse results."""
        eval_script = os.path.join(self.ar_dir, "eval.sh")
        if not os.path.exists(eval_script):
            return {"error": "No eval.sh found. Run init_session first."}

        start = time.time()
        try:
            result = subprocess.run(
                ["bash", eval_script],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=600,  # 10 min max
            )
            elapsed = time.time() - start
        except subprocess.TimeoutExpired:
            return {"error": "Eval timed out (600s)", "score": 0, "elapsed": 600}

        output = result.stdout + "\n" + result.stderr

        # Parse score
        score_match = re.search(r"score:([0-9.]+)", output)
        score = float(score_match.group(1)) if score_match else None

        # Parse metrics
        metrics = {}
        for m in re.finditer(r"metric:(\w+)=([0-9.]+)", output):
            metrics[m.group(1)] = float(m.group(2))

        # Parse total
        total_match = re.search(r"total:([0-9.]+)/([0-9.]+)", output)
        if total_match:
            metrics["passed"] = float(total_match.group(1))
            metrics["total"] = float(total_match.group(2))

        return {
            "score": score,
            "metrics": metrics,
            "exit_code": result.returncode,
            "elapsed": round(elapsed, 1),
            "output": output[-2000:],  # last 2000 chars
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
