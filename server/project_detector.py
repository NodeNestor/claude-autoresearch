"""Auto-detect project type and generate evaluation strategy."""

import os
import json
import glob as globmod


# Project type signatures: (indicator files/dirs, type name, eval strategy)
PROJECT_SIGNATURES = [
    # Web frameworks
    {
        "indicators": ["next.config.*", "app/layout.*", "pages/_app.*"],
        "type": "nextjs",
        "category": "webapp",
        "eval": {
            "setup": "npm install",
            "commands": [
                {"name": "typecheck", "cmd": "npx tsc --noEmit", "metric": "exit_code", "weight": 3.0},
                {"name": "lint", "cmd": "npx eslint . --max-warnings 0", "metric": "exit_code", "weight": 1.0},
                {"name": "test", "cmd": "npx jest --ci --passWithNoTests 2>&1 || npx vitest run 2>&1", "metric": "exit_code", "weight": 3.0},
                {"name": "build", "cmd": "npx next build 2>&1", "metric": "exit_code", "weight": 2.0},
                {"name": "bundle_size", "cmd": "du -sb .next/ 2>/dev/null | cut -f1", "metric": "lower_better", "weight": 0.5},
            ],
            "browser_eval": True,
            "browser_url": "http://localhost:3000",
            "browser_start": "npx next dev -p 3000",
        },
    },
    {
        "indicators": ["vite.config.*", "svelte.config.*", "vue.config.*", "angular.json"],
        "type": "spa",
        "category": "webapp",
        "eval": {
            "setup": "npm install",
            "commands": [
                {"name": "typecheck", "cmd": "npx tsc --noEmit 2>&1 || true", "metric": "exit_code", "weight": 2.0},
                {"name": "lint", "cmd": "npx eslint . 2>&1 || true", "metric": "exit_code", "weight": 1.0},
                {"name": "test", "cmd": "npx vitest run 2>&1 || npx jest --ci 2>&1 || true", "metric": "exit_code", "weight": 3.0},
                {"name": "build", "cmd": "npm run build 2>&1", "metric": "exit_code", "weight": 3.0},
            ],
            "browser_eval": True,
            "browser_url": "http://localhost:5173",
            "browser_start": "npm run dev",
        },
    },
    # Python
    {
        "indicators": ["train.py", "model.py", "*.ipynb"],
        "type": "ml_training",
        "category": "ml",
        "eval": {
            "commands": [
                {"name": "train_run", "cmd": "python train.py 2>&1", "metric": "extract_last_number", "pattern": r"val_loss[:\s=]+([0-9.]+)", "weight": 5.0, "direction": "lower"},
                {"name": "vram", "cmd": "nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1", "metric": "lower_better", "weight": 0.5},
            ],
            "time_budget": 300,
        },
    },
    {
        "indicators": ["manage.py", "django"],
        "type": "django",
        "category": "webapp",
        "eval": {
            "commands": [
                {"name": "check", "cmd": "python manage.py check 2>&1", "metric": "exit_code", "weight": 2.0},
                {"name": "test", "cmd": "python manage.py test --verbosity=0 2>&1", "metric": "exit_code", "weight": 5.0},
                {"name": "migrations", "cmd": "python manage.py makemigrations --check --dry-run 2>&1", "metric": "exit_code", "weight": 1.0},
            ],
            "browser_eval": True,
            "browser_url": "http://localhost:8000",
            "browser_start": "python manage.py runserver 8000",
        },
    },
    {
        "indicators": ["app.py", "main.py", "api.py"],
        "type": "python_app",
        "category": "backend",
        "eval": {
            "commands": [
                {"name": "typecheck", "cmd": "mypy . --ignore-missing-imports 2>&1 || pyright . 2>&1 || true", "metric": "exit_code", "weight": 1.0},
                {"name": "test", "cmd": "python -m pytest -x --tb=short 2>&1 || python -m unittest discover 2>&1", "metric": "exit_code", "weight": 5.0},
                {"name": "lint", "cmd": "ruff check . 2>&1 || flake8 . 2>&1 || true", "metric": "exit_code", "weight": 1.0},
            ],
        },
    },
    # Rust
    {
        "indicators": ["Cargo.toml"],
        "type": "rust",
        "category": "compiled",
        "eval": {
            "commands": [
                {"name": "check", "cmd": "cargo check 2>&1", "metric": "exit_code", "weight": 3.0},
                {"name": "test", "cmd": "cargo test 2>&1", "metric": "exit_code", "weight": 5.0},
                {"name": "clippy", "cmd": "cargo clippy -- -D warnings 2>&1 || true", "metric": "exit_code", "weight": 1.0},
                {"name": "binary_size", "cmd": "cargo build --release 2>&1 && du -b target/release/$(basename $(pwd)) 2>/dev/null | cut -f1", "metric": "lower_better", "weight": 0.5},
            ],
        },
    },
    # Go
    {
        "indicators": ["go.mod"],
        "type": "go",
        "category": "compiled",
        "eval": {
            "commands": [
                {"name": "build", "cmd": "go build ./... 2>&1", "metric": "exit_code", "weight": 3.0},
                {"name": "test", "cmd": "go test ./... 2>&1", "metric": "exit_code", "weight": 5.0},
                {"name": "vet", "cmd": "go vet ./... 2>&1", "metric": "exit_code", "weight": 1.0},
            ],
        },
    },
    # Generic Node.js
    {
        "indicators": ["package.json"],
        "type": "nodejs",
        "category": "backend",
        "eval": {
            "setup": "npm install",
            "commands": [
                {"name": "test", "cmd": "npm test 2>&1 || true", "metric": "exit_code", "weight": 5.0},
                {"name": "build", "cmd": "npm run build 2>&1 || true", "metric": "exit_code", "weight": 2.0},
                {"name": "lint", "cmd": "npm run lint 2>&1 || true", "metric": "exit_code", "weight": 1.0},
            ],
        },
    },
]


def detect_project(project_path: str) -> dict:
    """Detect project type by scanning for indicator files."""
    results = []

    for sig in PROJECT_SIGNATURES:
        score = 0
        matched = []
        for indicator in sig["indicators"]:
            pattern = os.path.join(project_path, indicator)
            matches = globmod.glob(pattern)
            if matches:
                score += 1
                matched.append(indicator)

        if score > 0:
            results.append({
                "type": sig["type"],
                "category": sig["category"],
                "confidence": score / len(sig["indicators"]),
                "matched": matched,
                "eval": sig["eval"],
            })

    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results[0] if results else None


def generate_eval_script(project_path: str, detection: dict) -> str:
    """Generate an eval.sh script for the detected project type."""
    eval_config = detection["eval"]
    lines = [
        "#!/bin/bash",
        f"# Auto-generated eval for {detection['type']} project",
        f"# Category: {detection['category']}",
        "set -euo pipefail",
        f'cd "{project_path}"',
        "",
        "SCORE=0",
        "TOTAL=0",
        "DETAILS=''",
        "",
    ]

    if eval_config.get("setup"):
        lines.append(f"# Setup")
        lines.append(f"{eval_config['setup']} > /dev/null 2>&1 || true")
        lines.append("")

    for cmd_def in eval_config.get("commands", []):
        name = cmd_def["name"]
        cmd = cmd_def["cmd"]
        weight = cmd_def.get("weight", 1.0)
        metric = cmd_def.get("metric", "exit_code")

        lines.append(f"# Eval: {name} (weight={weight})")

        if metric == "exit_code":
            lines.append(f"if {cmd} > /dev/null 2>&1; then")
            lines.append(f"  SCORE=$(echo \"$SCORE + {weight}\" | bc)")
            lines.append(f"  DETAILS=\"$DETAILS\\n{name}: PASS (+{weight})\"")
            lines.append(f"else")
            lines.append(f"  DETAILS=\"$DETAILS\\n{name}: FAIL (+0)\"")
            lines.append(f"fi")
            lines.append(f"TOTAL=$(echo \"$TOTAL + {weight}\" | bc)")
        elif metric == "lower_better":
            lines.append(f"VAL=$({cmd} 2>/dev/null || echo '999999')")
            lines.append(f"DETAILS=\"$DETAILS\\n{name}: $VAL\"")
            lines.append(f"echo \"metric:{name}=$VAL\"")
        elif metric == "extract_last_number":
            pattern = cmd_def.get("pattern", r"([0-9.]+)")
            lines.append(f"OUTPUT=$({cmd} 2>&1)")
            lines.append(f"VAL=$(echo \"$OUTPUT\" | grep -oP '{pattern}' | tail -1 || echo 'N/A')")
            lines.append(f"DETAILS=\"$DETAILS\\n{name}: $VAL\"")
            lines.append(f"echo \"metric:{name}=$VAL\"")

        lines.append("")

    lines.append("# Final score")
    lines.append("if [ \"$TOTAL\" != \"0\" ]; then")
    lines.append("  PCT=$(echo \"scale=2; $SCORE / $TOTAL * 100\" | bc)")
    lines.append("else")
    lines.append("  PCT=0")
    lines.append("fi")
    lines.append("echo \"score:$PCT\"")
    lines.append("echo -e \"$DETAILS\"")
    lines.append("echo \"total:$SCORE/$TOTAL\"")

    return "\n".join(lines)


def generate_program_md(project_path: str, detection: dict) -> str:
    """Generate a program.md (agent instructions) for the detected project type."""

    browser_section = ""
    if detection["eval"].get("browser_eval"):
        url = detection["eval"]["browser_url"]
        browser_section = f"""
## Browser Evaluation

After each code change, you MUST also verify the app works visually:
1. Start the dev server if not running: `{detection["eval"].get("browser_start", "npm run dev")}`
2. Navigate to {url}
3. Check that:
   - The page loads without errors
   - No console errors appear
   - Key UI elements render correctly
   - Interactive elements (buttons, forms, navigation) work
4. Report visual issues as part of the experiment result

Browser evaluation failures count as experiment failures — revert the change.
"""

    time_budget = detection["eval"].get("time_budget", "")
    time_section = ""
    if time_budget:
        time_section = f"""
## Time Budget

Each experiment has a fixed time budget of {time_budget} seconds.
The eval must complete within this window. If it doesn't, the experiment is a TIMEOUT and should be reverted.
"""

    return f"""# Autoresearch Program — {detection['type']}

You are an autonomous research agent improving this {detection['type']} project.
Your goal: make the project better through iterative experiments.

## Rules

1. **NEVER STOP.** Run experiments indefinitely until the human interrupts.
2. **One change at a time.** Each experiment = one focused modification.
3. **Always run eval.** After every change, run `bash .autoresearch/eval.sh` and check the score.
4. **Keep or revert.** If score improves (or stays same with cleaner code): KEEP. If score drops: REVERT with `git checkout -- .`
5. **Log everything.** After each experiment, use the `log_experiment` tool to record results.
6. **Git commit improvements.** When keeping, commit with a descriptive message.
7. **Stay in scope.** Only modify project source files. Never modify eval.sh or program.md.
8. **No new dependencies.** Unless explicitly allowed, work with what's already installed.

## What to Try

- Fix bugs, warnings, or code smells
- Improve performance (speed, memory, bundle size)
- Increase test coverage
- Refactor for clarity (only keep if tests still pass)
- Fix type errors or lint warnings
- Optimize hot paths
- Remove dead code
- Improve error handling at boundaries

## Simplicity Criterion

A tiny improvement that adds 20 lines of hacky code? Probably not worth it.
A tiny improvement from deleting code? Definitely keep.
When in doubt, prefer the simpler version.
{time_section}{browser_section}
## Experiment Format

For each experiment:
1. Describe what you're going to try (1 sentence)
2. Make the change
3. Run eval: `bash .autoresearch/eval.sh`
4. Decide: KEEP or REVERT
5. Log the result
6. Move to next experiment immediately — do NOT stop

## If You Run Out of Ideas

- Re-read the source code carefully
- Look at TODOs, FIXMEs, and HACKs
- Try combining ideas from previous near-miss experiments
- Try something radical — worst case it gets reverted
- Look at the test suite for edge cases
- Profile for performance bottlenecks
"""
