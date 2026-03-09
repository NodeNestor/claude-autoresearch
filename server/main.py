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
    "and writes the eval script YOU provide. Call scan_project first to understand "
    "the project, then decide on an eval command and pass it here.",
    {
        "properties": {
            "project_path": {"type": "string", "description": "Absolute path to the project root"},
            "eval_script": {"type": "string", "description": "Shell script content for evaluation. Must output 'score:NUMBER' where higher is better. You decide what commands to run based on the project."},
            "description": {"type": "string", "description": "What you want to improve"},
            "tag": {"type": "string", "description": "Optional tag for this session (default: timestamp)"},
            "program": {"type": "string", "description": "Optional custom program.md content — instructions for the research agent"},
        },
        "required": ["project_path", "eval_script"],
    },
)
def init_research(project_path: str, eval_script: str, description: str = "",
                  tag: str = None, program: str = None):
    """Initialize autoresearch session with agent-provided eval strategy."""
    if not os.path.isdir(project_path):
        return json.dumps({"error": f"{project_path} is not a directory"})

    tracker = ExperimentTracker(project_path)
    state = tracker.init_session(tag=tag, description=description)

    ar_dir = os.path.join(project_path, ".autoresearch")

    # Write the eval script provided by Claude
    eval_path = os.path.join(ar_dir, "eval.sh")
    with open(eval_path, "w", newline="\n") as f:
        f.write(eval_script)
    os.chmod(eval_path, 0o755)

    # Write program.md
    if program:
        program_content = program
    else:
        program_content = DEFAULT_PROGRAM.format(description=description or "general improvement")

    program_path = os.path.join(ar_dir, "program.md")
    with open(program_path, "w") as f:
        f.write(program_content)

    # Run baseline eval
    baseline = tracker.run_eval()
    if baseline.get("score") is not None:
        tracker.log_experiment("baseline", baseline["score"], baseline.get("metrics", {}), "baseline")
        state["best_score"] = baseline["score"]
        tracker.save_state(state)

    return json.dumps({
        "status": "initialized",
        "branch": state["branch"],
        "baseline_score": baseline.get("score"),
        "baseline_output": baseline.get("output", "")[-500:],
        "eval_script": eval_path,
        "program": program_path,
        "message": "Research session started. Read .autoresearch/program.md, then start experimenting!",
    }, indent=2)


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

## Rules

1. **NEVER STOP.** Run experiments until the human interrupts.
2. **One change at a time.** Each experiment = one focused modification.
3. **Always run eval.** After every change, use `run_eval` and check the score.
4. **Keep or revert.** Score improves → `keep_changes`. Score drops → `revert_changes`.
5. **Log everything.** After each experiment, use `log_experiment`.
6. **Stay in scope.** Don't modify eval.sh or program.md.

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
3. Run eval
4. Decide: KEEP or REVERT
5. Log the result
6. Move to next experiment immediately
"""


if __name__ == "__main__":
    server.run()
