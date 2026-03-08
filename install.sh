#!/bin/bash
set -euo pipefail
PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing claude-autoresearch..."

# Create venv if needed
if [ ! -d "$PLUGIN_ROOT/venv" ]; then
    echo "Creating Python venv..."
    python3 -m venv "$PLUGIN_ROOT/venv"
fi

# Register MCP server
CLAUDE_DIR="$HOME/.claude"
MCP_FILE="$CLAUDE_DIR/.mcp.json"
mkdir -p "$CLAUDE_DIR"

if [ -f "$MCP_FILE" ]; then
    # Add autoresearch server using python for JSON manipulation
    python3 -c "
import json, sys
with open('$MCP_FILE') as f:
    data = json.load(f)
data.setdefault('mcpServers', {})['autoresearch'] = {
    'command': 'bash',
    'args': ['run_server.sh'],
    'cwd': '$PLUGIN_ROOT'
}
with open('$MCP_FILE', 'w') as f:
    json.dump(data, f, indent=2)
"
else
    cat > "$MCP_FILE" << EOF
{
  "mcpServers": {
    "autoresearch": {
      "command": "bash",
      "args": ["run_server.sh"],
      "cwd": "$PLUGIN_ROOT"
    }
  }
}
EOF
fi

echo "claude-autoresearch installed!"
echo "MCP server registered. Restart Claude Code to activate."
