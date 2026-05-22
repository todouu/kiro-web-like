"""MCP configuration — reads real MCP server config from Kiro directories.

MCP servers are defined in JSON files:
  - ~/.kiro/settings/mcp.json    (global)
  - .kiro/settings/mcp.json      (workspace-scoped)

Format:
{
  "mcpServers": {
    "server-name": {
      "command": "command-to-run",
      "args": ["arg1", "arg2"],
      "env": {"KEY": "value"},
      "disabled": false,
      "autoApprove": ["tool1"],
      "disabledTools": ["tool2"]
    },
    "remote-server": {
      "url": "https://endpoint.example.com",
      "headers": {"HEADER": "value"},
      "disabled": false
    }
  }
}
"""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MCPServer:
    """An MCP server parsed from mcp.json."""

    id: str
    name: str
    transport: str  # "stdio" or "http"
    command: str = ""  # For stdio servers
    args: list[str] = field(default_factory=list)
    url: str = ""  # For HTTP/SSE servers
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    disabled: bool = False
    auto_approve: list[str] = field(default_factory=list)
    disabled_tools: list[str] = field(default_factory=list)
    scope: str = "global"  # "global" or "workspace"


def _parse_mcp_json(file_path: Path, scope: str) -> list[MCPServer]:
    """Parse an mcp.json file and return MCPServer objects."""
    servers = []

    if not file_path.exists():
        return servers

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return servers

    mcp_servers = data.get("mcpServers", {})

    for server_id, config in mcp_servers.items():
        # Determine transport type
        if "url" in config:
            transport = "http"
        else:
            transport = "stdio"

        command = config.get("command", "")
        args = config.get("args", [])

        # Build display command
        if command and args:
            display_cmd = f"{command} {' '.join(args)}"
        elif command:
            display_cmd = command
        else:
            display_cmd = config.get("url", "")

        server = MCPServer(
            id=server_id,
            name=server_id,
            transport=transport,
            command=display_cmd,
            args=args,
            url=config.get("url", ""),
            env=config.get("env", {}),
            headers=config.get("headers", {}),
            disabled=config.get("disabled", False),
            auto_approve=config.get("autoApprove", []),
            disabled_tools=config.get("disabledTools", []),
            scope=scope,
        )
        servers.append(server)

    return servers


def load_mcp_servers(workspace_path: Path | None = None) -> list[MCPServer]:
    """
    Load all MCP servers from global and workspace config files.

    Args:
        workspace_path: Optional workspace path to also scan .kiro/settings/mcp.json
    """
    servers = []

    # Global: ~/.kiro/settings/mcp.json
    global_file = Path.home() / ".kiro" / "settings" / "mcp.json"
    servers.extend(_parse_mcp_json(global_file, "global"))

    # Workspace: <workspace>/.kiro/settings/mcp.json
    if workspace_path:
        ws_file = workspace_path / ".kiro" / "settings" / "mcp.json"
        servers.extend(_parse_mcp_json(ws_file, "workspace"))

    return servers
