"""Stop hook — when Claude finishes, remind it to keep going (autoresearch never stops)."""

import os
import sys
import json


def main():
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        hook_input = {}

    cwd = hook_input.get("cwd", os.getcwd())
    state_file = os.path.join(cwd, ".autoresearch", "state.json")

    if not os.path.exists(state_file):
        print(json.dumps({"result": "continue"}))
        return

    try:
        with open(state_file) as f:
            state = json.load(f)
    except:
        print(json.dumps({"result": "continue"}))
        return

    exp_count = state.get("experiment_count", 0)
    best = state.get("best_score", "N/A")

    # Remind Claude to keep going
    message = (
        f"[autoresearch] Session still active! {exp_count} experiments done, best score: {best}.\n"
        f"REMEMBER: Never stop. Run the next experiment immediately.\n"
        f"If you're stuck, re-read the code, try something radical, or combine previous ideas."
    )

    result = {"result": "continue", "message": message}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
