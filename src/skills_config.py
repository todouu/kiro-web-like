"""Skills configuration — reads real skills from Kiro directories.

Skills are markdown files with YAML frontmatter located in:
  - ~/.kiro/skills/       (global, available across all workspaces)
  - .kiro/skills/         (workspace-scoped)

Each .md file has frontmatter like:
---
name: My Skill
description: What this skill does
---
(body with full instructions)
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Skill:
    """A skill parsed from a .kiro/skills/*.md file."""

    id: str
    name: str
    description: str
    file_path: str
    scope: str  # "global" or "workspace"
    content: str = ""  # Full markdown body (loaded on demand)


def _parse_frontmatter(file_path: Path) -> dict:
    """Parse YAML frontmatter from a markdown file."""
    try:
        text = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}

    # Match --- frontmatter ---
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", text, re.DOTALL)
    if not match:
        return {"_body": text}

    frontmatter_raw = match.group(1)
    body = match.group(2)

    # Simple YAML-like parsing (key: value per line)
    meta = {"_body": body}
    for line in frontmatter_raw.split("\n"):
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip('"').strip("'")

    return meta


def _scan_skills_dir(directory: Path, scope: str) -> list[Skill]:
    """Scan a directory for .md skill files."""
    skills = []

    if not directory.exists():
        return skills

    for md_file in sorted(directory.glob("*.md")):
        if md_file.name.startswith("_") or md_file.name.lower() == "readme.md":
            continue

        meta = _parse_frontmatter(md_file)
        name = meta.get("name", md_file.stem.replace("-", " ").replace("_", " ").title())
        description = meta.get("description", "")

        skill = Skill(
            id=md_file.stem,
            name=name,
            description=description,
            file_path=str(md_file),
            scope=scope,
            content=meta.get("_body", ""),
        )
        skills.append(skill)

    return skills


def load_skills(workspace_path: Path | None = None) -> list[Skill]:
    """
    Load all skills from global and workspace directories.

    Args:
        workspace_path: Optional workspace path to also scan for .kiro/skills/
    """
    skills = []

    # Global skills: ~/.kiro/skills/
    global_dir = Path.home() / ".kiro" / "skills"
    skills.extend(_scan_skills_dir(global_dir, "global"))

    # Workspace skills: <workspace>/.kiro/skills/
    if workspace_path:
        ws_dir = workspace_path / ".kiro" / "skills"
        skills.extend(_scan_skills_dir(ws_dir, "workspace"))

    return skills


def get_skill_content(skill: Skill) -> str:
    """Load the full content of a skill file."""
    try:
        path = Path(skill.file_path)
        text = path.read_text(encoding="utf-8")
        # Strip frontmatter
        match = re.match(r"^---\s*\n.*?\n---\s*\n?(.*)", text, re.DOTALL)
        return match.group(1) if match else text
    except (OSError, UnicodeDecodeError):
        return ""
