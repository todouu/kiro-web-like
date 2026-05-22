"""Agent configuration — reads real agent definitions from Kiro directories.

Custom agents are defined as JSON files in:
  - ~/.kiro/agents/*.json       (global)
  - .kiro/agents/*.json         (workspace-scoped)

JSON format:
{
  "name": "my-agent",
  "description": "What this agent does",
  "prompt": "System prompt or file://./prompt.md",
  "tools": ["read", "write", "shell"],
  "allowedTools": ["read"],
  "mcpServers": { ... }
}
"""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentConfig:
    """An agent parsed from .kiro/agents/*.json."""

    id: str
    name: str
    description: str
    prompt: str
    tools: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    mcp_servers: dict = field(default_factory=dict)
    scope: str = "global"  # "global" or "workspace"
    file_path: str = ""


def _parse_agent_json(file_path: Path, scope: str) -> AgentConfig | None:
    """Parse a JSON agent definition."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    return AgentConfig(
        id=file_path.stem,
        name=data.get("name", file_path.stem),
        description=data.get("description", ""),
        prompt=data.get("prompt", ""),
        tools=data.get("tools", []),
        allowed_tools=data.get("allowedTools", []),
        mcp_servers=data.get("mcpServers", {}),
        scope=scope,
        file_path=str(file_path),
    )


def _scan_agents_dir(directory: Path, scope: str) -> list[AgentConfig]:
    """Scan a directory for .json agent definition files."""
    agents = []

    if not directory.exists():
        return agents

    for agent_file in sorted(directory.glob("*.json")):
        if agent_file.name.startswith("_"):
            continue

        agent = _parse_agent_json(agent_file, scope)
        if agent:
            agents.append(agent)

    return agents


def load_agents(workspace_path: Path | None = None) -> list[AgentConfig]:
    """
    Load all agent definitions from global and workspace directories.

    Args:
        workspace_path: Optional workspace path to also scan .kiro/agents/
    """
    agents = []

    # Global agents: ~/.kiro/agents/*.json
    global_dir = Path.home() / ".kiro" / "agents"
    agents.extend(_scan_agents_dir(global_dir, "global"))

    # Workspace agents: <workspace>/.kiro/agents/*.json
    if workspace_path:
        ws_dir = workspace_path / ".kiro" / "agents"
        agents.extend(_scan_agents_dir(ws_dir, "workspace"))

    return agents


def get_agent(agent_id: str, workspace_path: Path | None = None) -> AgentConfig | None:
    """Get a specific agent by ID."""
    agents = load_agents(workspace_path)
    for agent in agents:
        if agent.id == agent_id:
            return agent
    return None


def list_agents(workspace_path: Path | None = None) -> list[AgentConfig]:
    """List all available agents."""
    return load_agents(workspace_path)
