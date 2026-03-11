# claude-autoresearch

Autonomous iterative improvement for **any** project type. Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch), adapted as a Claude Code plugin.

Point it at any project. It auto-detects the type, generates a fitness function, creates a git branch, and runs experiments in an infinite keep/revert loop — just like Karpathy's approach but for **everything**, not just ML.

## How It Works

```
init_research("./my-project")
  │
  ├── Detects: Next.js app
  ├── Generates: eval.sh (typecheck + lint + test + build + bundle size)
  ├── Generates: program.md (agent instructions)
  ├── Creates: git branch autoresearch/20260309-143022
  ├── Runs: baseline eval → score: 85.0
  │
  └── LOOP (forever):
       ├── Claude reads code, picks an improvement
       ├── Makes the change
       ├── Runs eval → score: 87.5 ✓ (KEEP, git commit)
       │   or
       │   Runs eval → score: 80.0 ✗ (REVERT, git checkout)
       ├── Logs to results.tsv
       └── Next experiment...
```

## Works With Any Project

Auto-detects your project type from config files (`package.json`, `Cargo.toml`, `go.mod`, `pyproject.toml`, etc.) and generates an appropriate eval script. No configuration needed — just point it at a repo and it figures out what to test.

You can also provide a custom eval command for any project type, or use the `claude_eval` tool where Claude reads the code and scores it itself — no scripts needed.

## MCP Tools

| Tool | Description |
|------|-------------|
| `init_research` | Initialize session — auto-detect, generate eval, create branch |
| `run_eval` | Run eval script, return score + metrics |
| `log_experiment` | Log experiment result (keep/revert/crash) |
| `keep_changes` | Git commit current changes |
| `revert_changes` | Git reset to last good state |
| `get_history` | View experiment history (results.tsv) |
| `get_summary` | Session stats: total, kept, reverted, best score |
| `end_research` | End session, return to base branch |
| `detect_project` | Preview auto-detection without initializing |
| `claude_eval` | Claude self-evaluates code quality (no scripts) |

## Git Tracking

Every experiment is tracked through git:
- Session starts on `autoresearch/<tag>` branch
- Successful experiments are committed with `[autoresearch]` prefix
- Failed experiments are reverted with `git checkout -- .`
- `results.tsv` logs every experiment with commit hash, score, metrics, status
- At the end, you can diff the branch against main to see all improvements

## Install

```bash
# Via marketplace
/plugin marketplace add https://github.com/NodeNestor/nestor-plugins

# Or manual
git clone https://github.com/NodeNestor/claude-autoresearch
cd claude-autoresearch
./install.sh  # or .\install.ps1 on Windows
```

## Usage

Just tell Claude:
```
Start autoresearch on this project
```

Or be specific:
```
Start autoresearch on E:\Repos\my-app — focus on reducing bundle size
```

Claude will initialize, read the program, and start the experiment loop autonomously.

## Part of the NodeNestor Suite

- **[rolling-context](https://github.com/NodeNestor/claude-rolling-context)** — Short-term: compress old messages, never hit context wall
- **[knowledge-graph](https://github.com/NodeNestor/claude-knowledge-graph)** — Long-term: persistent memory with semantic search
- **autoresearch** — Autonomous: iterative improvement with git tracking
