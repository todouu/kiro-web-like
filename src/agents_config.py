"""Agent configuration — reads real agent definitions from Kiro directories.

Custom agents are defined in:
  - ~/.kiro/agents/       (global)
  - .kiro/agents/         (workspace-scoped)

Each agent can be a .json or .md file.

JSON format:
{
  "name": "my-agent",
  "description": "What this agent does",
  "prompt": "System prompt or file://./prompt.md",
  "tools": ["read", "write", "shell"],
  "allowedTools": ["read"],
  "mcpServers": { ... }
}

Markdown format (.md):
---
name: My Agent
description: What this agent does
tools:
  - read
  - write
---
(Body is the system prompt)
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentConfig:
    """An agent parsed from .kiro/agents/."""

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


def _parse_agent_md(file_path: Path, scope: str) -> AgentConfig | None:
    """Parse a Markdown agent definition (with YAML frontmatter)."""
    try:
        text = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    # Parse frontmatter
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", text, re.DOTALL)
    if not match:
        # No frontmatter — treat entire file as prompt
        return AgentConfig(
            id=file_path.stem,
            name=file_path.stem.replace("-", " ").replace("_", " ").title(),
            description="",
            prompt=text,
            scope=scope,
            file_path=str(file_path),
        )

    frontmatter_raw = match.group(1)
    body = match.group(2)

    # Simple key: value parsing
    meta = {}
    for line in frontmatter_raw.split("\n"):
        line = line.strip()
        if ":" in line and not line.startswith("-"):
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip('"').strip("'")

    # Parse tools list (simple YAML list)
    tools = []
    in_tools = False
    for line in frontmatter_raw.split("\n"):
        stripped = line.strip()
        if stripped.startswith("tools:"):
            in_tools = True
            # Inline list?
            val = stripped.partition(":")[2].strip()
            if val.startswith("["):
                tools = [t.strip().strip('"').strip("'") for t in val.strip("[]").split(",")]
                in_tools = False
        elif in_tools and stripped.startswith("- "):
            tools.append(stripped[2:].strip())
        elif in_tools and not stripped.startswith("-"):
            in_tools = False

    return AgentConfig(
        id=file_path.stem,
        name=meta.get("name", file_path.stem.replace("-", " ").replace("_", " ").title()),
        description=meta.get("description", ""),
        prompt=body.strip(),
        tools=tools,
        scope=scope,
        file_path=str(file_path),
    )


def _scan_agents_dir(directory: Path, scope: str) -> list[AgentConfig]:
    """Scan a directory for agent definition files."""
    agents = []

    if not directory.exists():
        return agents

    for agent_file in sorted(directory.iterdir()):
        if agent_file.name.startswith("_") or agent_file.name.lower() == "readme.md":
            continue

        agent = None
        if agent_file.suffix == ".json":
            agent = _parse_agent_json(agent_file, scope)
        elif agent_file.suffix == ".md":
            agent = _parse_agent_md(agent_file, scope)

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

    # Global agents: ~/.kiro/agents/
    global_dir = Path.home() / ".kiro" / "agents"
    agents.extend(_scan_agents_dir(global_dir, "global"))

    # Workspace agents: <workspace>/.kiro/agents/
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
