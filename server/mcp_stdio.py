"""Minimal MCP 2.0 stdio server — same pattern as claude-knowledge-graph."""

import sys
import json
import traceback


class MCPServer:
    def __init__(self, name: str, version: str):
        self.name = name
        self.version = version
        self.tools: dict[str, dict] = {}
        self.handlers: dict[str, callable] = {}

    def tool(self, name: str, description: str, schema: dict):
        """Decorator to register an MCP tool."""
        def decorator(func):
            self.tools[name] = {
                "name": name,
                "description": description,
                "inputSchema": {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", []),
                },
            }
            self.handlers[name] = func
            return func
        return decorator

    def _handle_request(self, req: dict) -> dict:
        method = req.get("method", "")
        rid = req.get("id")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": self.name, "version": self.version},
                },
            }

        if method == "notifications/initialized":
            return None  # no response needed

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {"tools": list(self.tools.values())},
            }

        if method == "tools/call":
            tool_name = req["params"]["name"]
            args = req["params"].get("arguments", {})
            handler = self.handlers.get(tool_name)
            if not handler:
                return {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                        "isError": True,
                    },
                }
            try:
                result = handler(**args)
                if isinstance(result, str):
                    result = [{"type": "text", "text": result}]
                elif isinstance(result, dict):
                    result = [{"type": "text", "text": json.dumps(result, indent=2)}]
                return {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {"content": result},
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: {e}\n{traceback.format_exc()}"}],
                        "isError": True,
                    },
                }

        return {
            "jsonrpc": "2.0",
            "id": rid,
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
        }

    def run(self):
        """Read JSON-RPC from stdin, write to stdout."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            resp = self._handle_request(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
