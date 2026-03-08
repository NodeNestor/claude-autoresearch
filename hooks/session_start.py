"""SessionStart hook — detect active autoresearch session and inject program context."""

import os
import sys
import json


def main():
    # Read hook input from stdin
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        hook_input = {}

    # Get current working directory from hook context
    cwd = hook_input.get("cwd", os.getcwd())

    # Check for active autoresearch session
    ar_dir = os.path.join(cwd, ".autoresearch")
    state_file = os.path.join(ar_dir, "state.json")
    program_file = os.path.join(ar_dir, "program.md")

    if not os.path.exists(state_file):
        # No active session — just inform about availability
        result = {
            "result": "continue",
            "message": (
                "[autoresearch] No active session. "
                "Use the `init_research` tool to start autonomous improvement on this project."
            ),
        }
        print(json.dumps(result))
        return

    # Active session — inject program context
    try:
        with open(state_file) as f:
            state = json.load(f)
        program = ""
        if os.path.exists(program_file):
            with open(program_file) as f:
                program = f.read()
    except Exception as e:
        result = {"result": "continue", "message": f"[autoresearch] Error loading state: {e}"}
        print(json.dumps(result))
        return

    # Build injection message
    exp_count = state.get("experiment_count", 0)
    best = state.get("best_score", "N/A")
    branch = state.get("branch", "unknown")

    message = (
        f"[autoresearch] ACTIVE SESSION on branch `{branch}`\n"
        f"Experiments so far: {exp_count} | Best score: {best}\n"
        f"Description: {state.get('description', 'N/A')}\n\n"
        f"--- PROGRAM INSTRUCTIONS ---\n{program}\n--- END PROGRAM ---\n\n"
        f"Resume experimenting. Run `run_eval` to check current state, then continue the loop."
    )

    result = {"result": "continue", "message": message}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
