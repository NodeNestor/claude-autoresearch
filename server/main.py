"""Autoresearch MCP Server — autonomous iterative improvement for any project.

The agent (Claude) is the brain — it analyzes the project, decides the eval
strategy, and runs experiments. This server just provides the infrastructure:
scanning, tracking, git operations, and eval execution.
"""

import os
import json

from mcp_stdio import MCPServer
from project_detector import scan_project
from experiment import ExperimentTracker
from evaluator import parse_evaluator_config

server = MCPServer("autoresearch", "1.0.0")


@server.tool(
    "scan_project",
    "Scan a project directory and return its structure, config files, and stats. "
    "Use this to understand what kind of project it is before starting research. "
    "Returns file tree, config file contents (package.json, Cargo.toml, etc.), and extension stats. "
    "YOU decide what the project is and how to evaluate it based on this info.",
    {
        "properties": {
            "project_path": {"type": "string", "description": "Absolute path to the project root"},
            "max_depth": {"type": "integer", "description": "Max directory depth to scan (default: 3)"},
        },
        "required": ["project_path"],
    },
)
def scan_project_tool(project_path: str, max_depth: int = 3):
    if not os.path.isdir(project_path):
        return json.dumps({"error": f"{project_path} is not a directory"})
    result = scan_project(project_path, max_depth)
    return json.dumps(result, indent=2)


@server.tool(
    "init_research",
    "Initialize an autoresearch session. Creates a git branch, sets up tracking, "
    "and configures evaluation. Call scan_project first to understand the project, "
    "then decide on an eval strategy and pass it here.\n\n"
    "Evaluator types:\n"
    "- script: Shell script that outputs 'score:NUMBER' (default, fast, deterministic)\n"
    "- agent: YOU evaluate qualitatively using a rubric (for visual/UX/subjective quality)\n"
    "- hybrid: Script runs first as gate, then agent evaluates if script passes threshold",
    {
        "properties": {
            "project_path": {"type": "string", "description": "Absolute path to the project root"},
            "eval_script": {"type": "string", "description": "Shell script for evaluation (shorthand for script evaluator). Must output 'score:NUMBER'."},
            "evaluator": {
                "type": "object",
                "description": (
                    "Evaluator config object. Fields depend on type:\n"
                    "- type: 'script' | 'agent' | 'hybrid'\n"
                    "- script: shell script content (required for script/hybrid)\n"
                    "- rubric: markdown rubric for agent scoring (required for agent/hybrid)\n"
                    "- method: 'code-reading' | 'vision' | 'browser' | 'api' (default: code-reading)\n"
                    "- threshold: minimum script score to trigger agent eval (hybrid only, default: 0)\n"
                    "- weights: {script: 0.6, agent: 0.4} for hybrid scoring"
                ),
            },
            "description": {"type": "string", "description": "What you want to improve"},
            "tag": {"type": "string", "description": "Optional tag for this session (default: timestamp)"},
            "program": {"type": "string", "description": "Optional custom program.md content — instructions for the research agent"},
        },
        "required": ["project_path"],
    },
)
def init_research(project_path: str, eval_script: str = None, evaluator: dict = None,
                  description: str = "", tag: str = None, program: str = None):
    """Initialize autoresearch session with adaptive eval strategy."""
    if not os.path.isdir(project_path):
        return json.dumps({"error": f"{project_path} is not a directory"})

    # Resolve evaluator config
    if eval_script and evaluator:
        return json.dumps({"error": "Provide eval_script OR evaluator, not both."})
    if not eval_script and not evaluator:
        return json.dumps({"error": "Provide eval_script (string) or evaluator (config object)."})

    try:
        config = parse_evaluator_config(evaluator if evaluator else eval_script)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    tracker = ExperimentTracker(project_path)
    state = tracker.init_session(tag=tag, description=description)

    ar_dir = os.path.join(project_path, ".autoresearch")

    # Save evaluator config
    tracker.save_evaluator_config(config)

    # Write eval.sh if config includes a script
    eval_path = None
    if config.get("script"):
        eval_path = os.path.join(ar_dir, "eval.sh")
        with open(eval_path, "w", newline="\n") as f:
            f.write(config["script"])
        os.chmod(eval_path, 0o755)

    # Write rubric.md if config includes a rubric
    if config.get("rubric"):
        rubric_path = os.path.join(ar_dir, "rubric.md")
        with open(rubric_path, "w") as f:
            f.write(config["rubric"])

    # Write program.md
    eval_type = config.get("type", "script")
    if program:
        program_content = program
    else:
        program_content = DEFAULT_PROGRAM.format(
            description=description or "general improvement",
            eval_type=eval_type,
        )

    program_path = os.path.join(ar_dir, "program.md")
    with open(program_path, "w") as f:
        f.write(program_content)

    # Run baseline eval (for script/hybrid, runs immediately; for agent, returns prompt)
    baseline = tracker.run_eval()

    result = {
        "status": "initialized",
        "branch": state["branch"],
        "evaluator_type": eval_type,
        "program": program_path,
        "message": "Research session started. Read .autoresearch/program.md, then start experimenting!",
    }

    if baseline.get("agent_eval_required"):
        # Agent/hybrid baseline — agent needs to score it
        result["baseline_requires_agent_eval"] = True
        result["eval_prompt"] = baseline.get("prompt", "")
        result["message"] += " First, evaluate the baseline by reading the prompt and calling submit_eval_score."
    elif baseline.get("score") is not None:
        tracker.log_experiment("baseline", baseline["score"], baseline.get("metrics", {}), "baseline")
        state["best_score"] = baseline["score"]
        tracker.save_state(state)
        result["baseline_score"] = baseline["score"]
        result["baseline_output"] = baseline.get("output", "")[-500:]

    if eval_path:
        result["eval_script"] = eval_path

    return json.dumps(result, indent=2)


@server.tool(
    "run_eval",
    "Run the evaluation script and return the score + metrics. Call this after every code change.",
    {
        "properties": {
            "project_path": {"type": "string", "description": "Project root path"},
        },
        "required": ["project_path"],
    },
)
def run_eval(project_path: str):
    tracker = ExperimentTracker(project_path)
    result = tracker.run_eval()
    return json.dumps(result, indent=2)


@server.tool(
    "submit_eval_score",
    "Submit your evaluation score after an agent or hybrid eval. "
    "Call this after run_eval returns agent_eval_required=true. "
    "Read the rubric, evaluate honestly, then submit your score here.",
    {
        "properties": {
            "project_path": {"type": "string", "description": "Project root path"},
            "score": {"type": "number", "description": "Your score based on the rubric (0-100)"},
            "metrics": {"type": "object", "description": "Optional metrics from your evaluation (e.g., {correctness: 20, design: 15})"},
            "assessment": {"type": "string", "description": "Brief qualitative assessment (1-3 sentences)"},
        },
        "required": ["project_path", "score"],
    },
)
def submit_eval_score(project_path: str, score: float, metrics: dict = None,
                      assessment: str = None):
    tracker = ExperimentTracker(project_path)
    result = tracker.submit_eval_score(score, metrics, assessment)
    return json.dumps(result, indent=2)


@server.tool(
    "log_experiment",
    "Log an experiment result. Call after deciding to keep or revert.",
    {
        "properties": {
            "project_path": {"type": "string", "description": "Project root path"},
            "description": {"type": "string", "description": "What was tried (1 sentence)"},
            "score": {"type": "number", "description": "Score from eval"},
            "metrics": {"type": "object", "description": "Additional metrics dict"},
            "status": {"type": "string", "enum": ["keep", "revert", "crash"], "description": "Experiment outcome"},
        },
        "required": ["project_path", "description", "score", "status"],
    },
)
def log_experiment(project_path: str, description: str, score: float,
                   status: str, metrics: dict = None):
    tracker = ExperimentTracker(project_path)
    result = tracker.log_experiment(description, score, metrics or {}, status)
    return json.dumps(result, indent=2)


@server.tool(
    "keep_changes",
    "Git commit the current changes as a successful experiment.",
    {
        "properties": {
            "project_path": {"type": "string", "description": "Project root path"},
            "message": {"type": "string", "description": "Commit message describing the improvement"},
        },
        "required": ["project_path", "message"],
    },
)
def keep_changes(project_path: str, message: str):
    tracker = ExperimentTracker(project_path)
    result = tracker.keep_experiment(message)
    return json.dumps(result, indent=2)


@server.tool(
    "revert_changes",
    "Revert all changes back to the last good state. Call when an experiment fails.",
    {
        "properties": {
            "project_path": {"type": "string", "description": "Project root path"},
        },
        "required": ["project_path"],
    },
)
def revert_changes(project_path: str):
    tracker = ExperimentTracker(project_path)
    result = tracker.revert_experiment()
    return json.dumps(result, indent=2)


@server.tool(
    "get_history",
    "Get experiment history — see what's been tried and what worked.",
    {
        "properties": {
            "project_path": {"type": "string", "description": "Project root path"},
            "limit": {"type": "integer", "description": "Max results (default 50)"},
        },
        "required": ["project_path"],
    },
)
def get_history(project_path: str, limit: int = 50):
    tracker = ExperimentTracker(project_path)
    history = tracker.get_history(limit)
    return json.dumps(history, indent=2)


@server.tool(
    "get_summary",
    "Get a summary of the current autoresearch session — total experiments, kept, reverted, best score.",
    {
        "properties": {
            "project_path": {"type": "string", "description": "Project root path"},
        },
        "required": ["project_path"],
    },
)
def get_summary(project_path: str):
    tracker = ExperimentTracker(project_path)
    summary = tracker.get_summary()
    return json.dumps(summary, indent=2)


@server.tool(
    "end_research",
    "End the autoresearch session and return to the base branch.",
    {
        "properties": {
            "project_path": {"type": "string", "description": "Project root path"},
        },
        "required": ["project_path"],
    },
)
def end_research(project_path: str):
    tracker = ExperimentTracker(project_path)
    result = tracker.end_session()
    return json.dumps(result, indent=2)


DEFAULT_PROGRAM = """# Autoresearch Program

You are an autonomous research agent improving this project.
Goal: {description}
Evaluator: {eval_type}

## Rules

1. **NEVER STOP.** Run experiments until the human interrupts.
2. **One change at a time.** Each experiment = one focused modification.
3. **Always run eval.** After every change, use `run_eval` and check the score.
4. **Keep or revert.** Score improves → `keep_changes`. Score drops → `revert_changes`.
5. **Log everything.** After each experiment, use `log_experiment`.
6. **Stay in scope.** Don't modify eval.sh, rubric.md, or program.md.

## Evaluation Flow

### If evaluator is `script`:
- `run_eval` returns a score directly. Use it for keep/revert.

### If evaluator is `agent`:
- `run_eval` returns `agent_eval_required: true` with a rubric and context.
- Read the rubric carefully.
- Evaluate the current state **honestly** — score inflation defeats the purpose.
- Call `submit_eval_score` with your score (0-100), optional metrics, and assessment.
- Use the returned score for keep/revert.

### If evaluator is `hybrid`:
- `run_eval` runs the script first. If below threshold, returns score directly (skip agent).
- If above threshold, returns `agent_eval_required: true` — same as agent flow.
- The final score is a weighted combination of script and agent scores.

## What to Try

- Fix bugs, warnings, or code smells
- Improve performance
- Increase test coverage
- Refactor for clarity (only keep if tests still pass)
- Fix type errors or lint warnings
- Remove dead code
- Improve error handling at boundaries

## Experiment Flow

1. Describe what you're going to try (1 sentence)
2. Make the change
3. Run eval (and submit_eval_score if agent eval required)
4. Decide: KEEP or REVERT
5. Log the result
6. Move to next experiment immediately
"""


if __name__ == "__main__":
    server.run()
