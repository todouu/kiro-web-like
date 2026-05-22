"""Read conversation history from kiro-cli session files.

Kiro persists sessions to ~/.kiro/sessions/cli/:
  <session-id>.jsonl  — event log with Prompt / AssistantMessage entries
"""

import json
from pathlib import Path

KIRO_SESSIONS_DIR = Path.home() / ".kiro" / "sessions" / "cli"


def load_messages(acp_session_id: str) -> list[dict]:
    """Return chat messages [{role, content}] from a kiro jsonl session file."""
    jsonl = KIRO_SESSIONS_DIR / f"{acp_session_id}.jsonl"
    if not jsonl.exists():
        return []

    messages = []
    try:
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            kind = event.get("kind")
            data = event.get("data", {})

            if kind == "Prompt":
                text = " ".join(
                    c["data"] for c in data.get("content", []) if c.get("kind") == "text"
                )
                if text:
                    messages.append({"role": "user", "content": text})

            elif kind == "AssistantMessage":
                text = " ".join(
                    c["data"] for c in data.get("content", []) if c.get("kind") == "text"
                )
                if text:
                    messages.append({"role": "assistant", "content": text})

    except (json.JSONDecodeError, OSError):
        pass

    return messages
