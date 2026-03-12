"""Evaluator strategies — script, agent, and hybrid evaluation."""

import os
import json
import subprocess
import time
import re


def parse_evaluator_config(config):
    """Normalize evaluator config. Accepts a string (eval script) or dict."""
    if isinstance(config, str):
        return {"type": "script", "script": config}

    if not isinstance(config, dict):
        raise ValueError("evaluator must be a string (eval script) or config object")

    eval_type = config.get("type", "script")
    if eval_type not in ("script", "agent", "hybrid"):
        raise ValueError(f"Unknown evaluator type: {eval_type}. Must be script, agent, or hybrid.")

    if eval_type == "script" and "script" not in config:
        raise ValueError("Script evaluator requires 'script' field")

    if eval_type == "agent" and "rubric" not in config:
        raise ValueError("Agent evaluator requires 'rubric' field")

    if eval_type == "hybrid":
        if "script" not in config:
            raise ValueError("Hybrid evaluator requires 'script' field")
        if "rubric" not in config:
            raise ValueError("Hybrid evaluator requires 'rubric' field")

    return config


def parse_script_output(output: str) -> dict:
    """Parse score, metrics, and totals from eval script output."""
    score_match = re.search(r"score:([0-9.]+)", output)
    score = float(score_match.group(1)) if score_match else None

    metrics = {}
    for m in re.finditer(r"metric:(\w+)=([0-9.]+)", output):
        metrics[m.group(1)] = float(m.group(2))

    total_match = re.search(r"total:([0-9.]+)/([0-9.]+)", output)
    if total_match:
        metrics["passed"] = float(total_match.group(1))
        metrics["total"] = float(total_match.group(2))

    return {"score": score, "metrics": metrics}


class ScriptEvaluator:
    """Run a shell script and parse score from output."""

    def __init__(self, project_path: str, ar_dir: str):
        self.project_path = project_path
        self.ar_dir = ar_dir

    def run(self) -> dict:
        eval_script = os.path.join(self.ar_dir, "eval.sh")
        if not os.path.exists(eval_script):
            return {"error": "No eval.sh found. Run init_research first."}

        start = time.time()
        try:
            result = subprocess.run(
                ["bash", eval_script],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=600,
            )
            elapsed = time.time() - start
        except subprocess.TimeoutExpired:
            return {"error": "Eval timed out (600s)", "score": 0, "elapsed": 600}

        output = result.stdout + "\n" + result.stderr
        parsed = parse_script_output(output)

        return {
            "score": parsed["score"],
            "metrics": parsed["metrics"],
            "exit_code": result.returncode,
            "elapsed": round(elapsed, 1),
            "output": output[-2000:],
            "strategy": "script",
        }


class AgentEvaluator:
    """Prepare context and rubric for the calling Claude agent to self-evaluate."""

    def __init__(self, project_path: str, config: dict):
        self.project_path = project_path
        self.config = config

    def _gather_context(self) -> str:
        """Gather evaluation context based on the configured method."""
        method = self.config.get("method", "code-reading")
        context_parts = []

        if method in ("code-reading", "hybrid"):
            # Get git diff for what changed
            try:
                result = subprocess.run(
                    ["git", "diff", "HEAD"],
                    cwd=self.project_path,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                diff = result.stdout.strip()
                if not diff:
                    # Try diff of last commit
                    result = subprocess.run(
                        ["git", "diff", "HEAD~1..HEAD"],
                        cwd=self.project_path,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    diff = result.stdout.strip()
                if diff:
                    context_parts.append(f"## Git Diff\n```diff\n{diff[:5000]}\n```")
            except Exception:
                context_parts.append("## Git Diff\n(unable to get diff)")

        if method == "vision":
            # Point to screenshot directory for the agent to inspect
            screenshots_dir = os.path.join(self.project_path, ".autoresearch", "screenshots")
            if os.path.isdir(screenshots_dir):
                files = os.listdir(screenshots_dir)
                if files:
                    context_parts.append(
                        f"## Screenshots\nInspect these files visually:\n"
                        + "\n".join(f"- {os.path.join(screenshots_dir, f)}" for f in sorted(files))
                    )
            else:
                context_parts.append(
                    "## Screenshots\nNo screenshots found. "
                    "Take screenshots of the application and save them to "
                    f"`{screenshots_dir}/` before evaluating."
                )

        if method == "browser":
            context_parts.append(
                "## Browser Testing\n"
                "Use your browser tools to navigate the application and evaluate it. "
                "Check the URL, interactions, visual appearance, and functionality."
            )

        if method == "api":
            logs_dir = os.path.join(self.project_path, ".autoresearch", "api_logs")
            if os.path.isdir(logs_dir):
                files = os.listdir(logs_dir)
                if files:
                    context_parts.append(
                        f"## API Logs\nReview these response logs:\n"
                        + "\n".join(f"- {os.path.join(logs_dir, f)}" for f in sorted(files))
                    )
            else:
                context_parts.append(
                    "## API Testing\n"
                    "Make API requests to test the endpoints and evaluate responses."
                )

        return "\n\n".join(context_parts) if context_parts else "(no additional context)"

    def prepare(self) -> dict:
        """Prepare the evaluation prompt for the calling agent."""
        rubric = self.config["rubric"]
        context = self._gather_context()
        method = self.config.get("method", "code-reading")

        prompt = (
            f"# Agent Evaluation Required\n\n"
            f"Evaluate the current state of the project using the rubric below. "
            f"Be honest and critical — score inflation defeats the purpose.\n\n"
            f"## Rubric\n{rubric}\n\n"
            f"## Context\n{context}\n\n"
            f"## Instructions\n"
            f"1. Review the {'code changes' if method == 'code-reading' else 'application state'} carefully\n"
            f"2. Score each criterion in the rubric\n"
            f"3. Call `submit_eval_score` with your total score (0-100), metrics, and a brief assessment\n"
        )

        return {
            "score": None,
            "agent_eval_required": True,
            "strategy": "agent",
            "method": method,
            "prompt": prompt,
            "message": "Agent evaluation needed. Read the prompt, evaluate, then call submit_eval_score.",
        }


class HybridEvaluator:
    """Run script first as a gate, then agent for qualitative assessment."""

    def __init__(self, project_path: str, ar_dir: str, config: dict, save_state_fn=None):
        self.project_path = project_path
        self.ar_dir = ar_dir
        self.config = config
        self._save_state_fn = save_state_fn  # callback to persist pending script score

    def run(self) -> dict:
        # Run script first
        script_eval = ScriptEvaluator(self.project_path, self.ar_dir)
        script_result = script_eval.run()

        if script_result.get("error"):
            return script_result

        script_score = script_result.get("score")
        threshold = self.config.get("threshold", 0)

        # If below threshold, skip agent eval
        if script_score is not None and script_score < threshold:
            return {
                "score": script_score,
                "metrics": script_result.get("metrics", {}),
                "exit_code": script_result.get("exit_code"),
                "elapsed": script_result.get("elapsed"),
                "output": script_result.get("output", ""),
                "strategy": "hybrid",
                "gated": True,
                "message": f"Script score {script_score} below threshold {threshold} — agent eval skipped.",
            }

        # Above threshold — save pending script score and prepare agent eval
        if self._save_state_fn:
            self._save_state_fn(script_score)

        agent_eval = AgentEvaluator(self.project_path, self.config)
        agent_result = agent_eval.prepare()

        # Include script results so submit_eval_score can compute weighted final
        agent_result["strategy"] = "hybrid"
        agent_result["script_score"] = script_score
        agent_result["script_metrics"] = script_result.get("metrics", {})
        agent_result["script_elapsed"] = script_result.get("elapsed")
        agent_result["script_output"] = script_result.get("output", "")[-500:]
        agent_result["weights"] = self.config.get("weights", {"script": 0.6, "agent": 0.4})
        agent_result["message"] = (
            f"Script passed (score: {script_score}). "
            "Now do the agent evaluation — read the prompt, evaluate, then call submit_eval_score."
        )

        return agent_result


def compute_hybrid_score(script_score: float, agent_score: float,
                         weights: dict = None) -> float:
    """Compute weighted hybrid score from script and agent scores."""
    if weights is None:
        weights = {"script": 0.6, "agent": 0.4}
    w_script = weights.get("script", 0.6)
    w_agent = weights.get("agent", 0.4)
    return round(w_script * script_score + w_agent * agent_score, 2)
