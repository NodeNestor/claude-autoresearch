"""Autoresearch MCP Server — autonomous iterative improvement for any project."""

import os
import json
import subprocess

from mcp_stdio import MCPServer
from project_detector import detect_project, generate_eval_script, generate_program_md
from experiment import ExperimentTracker

server = MCPServer("autoresearch", "1.0.0")


@server.tool(
    "init_research",
    "Initialize autoresearch on a project. Auto-detects project type, generates eval script and program instructions. Call this once to start.",
    {
        "properties": {
            "project_path": {"type": "string", "description": "Absolute path to the project root"},
            "tag": {"type": "string", "description": "Optional tag for this research session (default: timestamp)"},
            "description": {"type": "string", "description": "What you want to improve"},
            "custom_eval": {"type": "string", "description": "Optional custom eval command (overrides auto-detection)"},
            "editable_files": {"type": "string", "description": "Glob pattern of files the agent can edit (default: all source files)"},
        },
        "required": ["project_path"],
    },
)
def init_research(project_path: str, tag: str = None, description: str = "",
                  custom_eval: str = None, editable_files: str = None):
    """Initialize autoresearch session."""
    if not os.path.isdir(project_path):
        return f"Error: {project_path} is not a directory"

    # Detect project type
    detection = detect_project(project_path)
    if not detection and not custom_eval:
        return json.dumps({
            "error": "Could not auto-detect project type. Please provide custom_eval command.",
            "hint": "custom_eval should be a shell command that outputs 'score:NUMBER' where higher is better",
        })

    tracker = ExperimentTracker(project_path)
    state = tracker.init_session(tag=tag, description=description)

    ar_dir = os.path.join(project_path, ".autoresearch")

    # Generate or write eval script
    if custom_eval:
        eval_content = f"#!/bin/bash\ncd \"{project_path}\"\n{custom_eval}\n"
        detection = detection or {"type": "custom", "category": "custom", "eval": {}}
    else:
        eval_content = generate_eval_script(project_path, detection)

    eval_path = os.path.join(ar_dir, "eval.sh")
    with open(eval_path, "w", newline="\n") as f:
        f.write(eval_content)
    os.chmod(eval_path, 0o755)

    # Generate program.md
    program_content = generate_program_md(project_path, detection)
    if editable_files:
        program_content += f"\n## Editable Files\n\nOnly modify files matching: `{editable_files}`\n"

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
        "project_type": detection["type"],
        "category": detection["category"],
        "branch": state["branch"],
        "baseline_score": baseline.get("score"),
        "baseline_metrics": baseline.get("metrics", {}),
        "eval_script": eval_path,
        "program": program_path,
        "message": f"Autoresearch initialized for {detection['type']} project. Read .autoresearch/program.md for instructions, then start experimenting!",
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


@server.tool(
    "detect_project",
    "Auto-detect project type without initializing. Useful for previewing what eval strategy will be used.",
    {
        "properties": {
            "project_path": {"type": "string", "description": "Project root path"},
        },
        "required": ["project_path"],
    },
)
def detect_project_tool(project_path: str):
    detection = detect_project(project_path)
    if not detection:
        return json.dumps({"error": "Could not detect project type", "hint": "Use custom_eval parameter"})
    return json.dumps(detection, indent=2)


@server.tool(
    "claude_eval",
    "Have Claude itself evaluate the current state of the project by reading code and judging quality. "
    "This is the 'Claude IS the fitness function' mode — no scripts needed, Claude reads the code and scores it. "
    "Use this for subjective improvements like code quality, readability, architecture.",
    {
        "properties": {
            "project_path": {"type": "string", "description": "Project root path"},
            "focus": {"type": "string", "description": "What to evaluate (e.g., 'code quality', 'readability', 'architecture', 'performance patterns')"},
            "files": {"type": "string", "description": "Comma-separated file paths to evaluate (relative to project root)"},
        },
        "required": ["project_path", "focus"],
    },
)
def claude_eval(project_path: str, focus: str, files: str = None):
    """Return structured prompt for Claude to self-evaluate.

    Claude IS the fitness function here — it reads the code and judges.
    The MCP tool returns the evaluation framework, Claude does the actual judging.
    """
    # Gather file contents for Claude to evaluate
    file_list = []
    if files:
        for f in files.split(","):
            fp = os.path.join(project_path, f.strip())
            if os.path.exists(fp):
                try:
                    with open(fp) as fh:
                        content = fh.read()
                    file_list.append({"path": f.strip(), "content": content[:10000]})
                except:
                    file_list.append({"path": f.strip(), "error": "Could not read"})
    else:
        # Auto-find key files
        for root, dirs, fnames in os.walk(project_path):
            # Skip hidden dirs, node_modules, etc.
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in
                      ("node_modules", "__pycache__", "venv", ".venv", "dist", "build", "target")]
            for fname in fnames:
                if any(fname.endswith(ext) for ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java")):
                    rel = os.path.relpath(os.path.join(root, fname), project_path)
                    try:
                        with open(os.path.join(root, fname)) as fh:
                            content = fh.read()
                        file_list.append({"path": rel, "content": content[:5000]})
                    except:
                        pass
                if len(file_list) >= 20:  # cap at 20 files
                    break
            if len(file_list) >= 20:
                break

    return json.dumps({
        "eval_type": "claude_self_eval",
        "focus": focus,
        "instruction": (
            f"You are evaluating this project for: {focus}\n\n"
            "Score each file on a scale of 1-10 based on the focus criteria.\n"
            "Then provide an overall score (1-10) and specific actionable improvements.\n\n"
            "Output format:\n"
            "- Per-file scores with brief justification\n"
            "- Overall score as: score:X.X\n"
            "- Top 3 concrete improvements to try next\n"
        ),
        "files": file_list,
        "file_count": len(file_list),
    }, indent=2)


if __name__ == "__main__":
    server.run()
