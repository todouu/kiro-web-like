"""Skills configuration — reads real skills from Kiro directories.

Skills are stored as subdirectories under:
  - ~/.kiro/skills/<skill-name>/SKILL.md       (global)
  - .kiro/skills/<skill-name>/SKILL.md         (workspace-scoped)

Each SKILL.md has YAML frontmatter:
---
name: My Skill
description: What this skill does
---
(body with full instructions)
"""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    """A skill parsed from a .kiro/skills/<name>/SKILL.md file."""

    id: str
    name: str
    description: str
    file_path: str
    scope: str  # "global" or "workspace"
    content: str = ""  # Full markdown body


def _parse_skill_md(file_path: Path) -> dict:
    """Parse YAML frontmatter from a SKILL.md file."""
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
    """Scan a skills directory for <skill-name>/SKILL.md files."""
    skills = []

    if not directory.exists():
        return skills

    for skill_dir in sorted(directory.iterdir()):
        if not skill_dir.is_dir():
            continue
        if skill_dir.name.startswith("_") or skill_dir.name.startswith("."):
            continue

        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue

        meta = _parse_skill_md(skill_file)
        name = meta.get("name", skill_dir.name.replace("-", " ").replace("_", " ").title())
        description = meta.get("description", "")

        skill = Skill(
            id=skill_dir.name,
            name=name,
            description=description,
            file_path=str(skill_file),
            scope=scope,
            content=meta.get("_body", ""),
        )
        skills.append(skill)

    return skills


def load_skills(workspace_path: Path | None = None) -> list[Skill]:
    """
    Load all skills from global and workspace directories.

    Scans ~/.kiro/skills/<name>/SKILL.md and .kiro/skills/<name>/SKILL.md
    """
    skills = []

    # Global skills: ~/.kiro/skills/*/SKILL.md
    global_dir = Path.home() / ".kiro" / "skills"
    skills.extend(_scan_skills_dir(global_dir, "global"))

    # Workspace skills: <workspace>/.kiro/skills/*/SKILL.md
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
