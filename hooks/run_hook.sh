#!/bin/bash
# Universal hook launcher — same pattern as claude-knowledge-graph
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(dirname "$SCRIPT_DIR")"

# Activate venv if it exists
if [ -f "$PLUGIN_ROOT/venv/bin/activate" ]; then
    source "$PLUGIN_ROOT/venv/bin/activate"
elif [ -f "$PLUGIN_ROOT/venv/Scripts/activate" ]; then
    source "$PLUGIN_ROOT/venv/Scripts/activate"
fi

# Run the hook script, passing stdin through
python "$SCRIPT_DIR/$1" 2>/dev/null
