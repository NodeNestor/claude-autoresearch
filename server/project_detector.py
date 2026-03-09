"""Project scanner — gathers raw context for Claude to analyze."""

import os
import json


# Key config files that reveal project type — just check existence + read content
CONFIG_FILES = [
    "package.json", "tsconfig.json", "next.config.js", "next.config.ts", "next.config.mjs",
    "vite.config.ts", "vite.config.js", "webpack.config.js",
    "Cargo.toml", "go.mod", "go.sum",
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile",
    "Makefile", "CMakeLists.txt", "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "pom.xml", "build.gradle", "build.gradle.kts",
    ".eslintrc.json", ".eslintrc.js", "prettier.config.js",
    "jest.config.js", "jest.config.ts", "vitest.config.ts",
    "manage.py", "app.py", "main.py", "train.py",
    "CLAUDE.md", "README.md",
]


def scan_project(project_path: str, max_depth: int = 3) -> dict:
    """Scan project and return raw context for Claude to analyze.

    Returns file tree, config file contents, and basic stats.
    Claude decides what the project is and how to evaluate it.
    """
    result = {
        "path": project_path,
        "config_files": {},
        "file_tree": [],
        "stats": {
            "total_files": 0,
            "extensions": {},
        },
    }

    # Read config files
    for cf in CONFIG_FILES:
        fp = os.path.join(project_path, cf)
        if os.path.exists(fp):
            try:
                with open(fp) as f:
                    content = f.read(4000)  # first 4KB
                result["config_files"][cf] = content
            except Exception:
                result["config_files"][cf] = "<could not read>"

    # Walk file tree (limited depth)
    skip_dirs = {
        "node_modules", "__pycache__", ".git", ".venv", "venv",
        "dist", "build", "target", ".next", ".nuxt", "coverage",
        ".autoresearch", ".claude", ".idea", ".vscode",
    }

    for root, dirs, files in os.walk(project_path):
        # Compute depth
        rel = os.path.relpath(root, project_path)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth >= max_depth:
            dirs.clear()
            continue

        # Skip irrelevant dirs
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]

        for fname in files:
            rel_path = os.path.relpath(os.path.join(root, fname), project_path)
            result["file_tree"].append(rel_path)
            result["stats"]["total_files"] += 1

            # Track extensions
            ext = os.path.splitext(fname)[1].lower()
            if ext:
                result["stats"]["extensions"][ext] = result["stats"]["extensions"].get(ext, 0) + 1

    # Sort extensions by count
    result["stats"]["extensions"] = dict(
        sorted(result["stats"]["extensions"].items(), key=lambda x: -x[1])
    )

    # Cap file tree at 200 entries
    if len(result["file_tree"]) > 200:
        result["file_tree"] = result["file_tree"][:200]
        result["stats"]["tree_truncated"] = True

    return result
