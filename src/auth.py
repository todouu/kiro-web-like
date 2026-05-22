"""User authentication and session management."""

import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import bcrypt
import yaml

from src.config import config


@dataclass
class User:
    """Represents an authenticated user."""

    username: str
    email: str
    display_name: str
    created_at: float = field(default_factory=time.time)


@dataclass
class Session:
    """Represents a user session."""

    session_id: str
    username: str
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    agent_id: str = ""
    title: str = ""
    acp_session_ids: dict = field(default_factory=dict)  # agent_id -> kiro-cli session_id


class AuthManager:
    """Manages user registration, login, and sessions."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or config.data_dir
        self.users_file = self.data_dir / "users.yaml"
        self.sessions_dir = self.data_dir / "sessions"
        self._ensure_users_file()
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_users_file(self):
        """Create users file if it doesn't exist."""
        if not self.users_file.exists():
            self.users_file.parent.mkdir(parents=True, exist_ok=True)
            self._save_users({})

    def _load_users(self) -> dict:
        """Load users from YAML file."""
        if not self.users_file.exists():
            return {}
        with open(self.users_file, "r") as f:
            data = yaml.safe_load(f)
            return data if data else {}

    def _save_users(self, users: dict):
        """Save users to YAML file."""
        with open(self.users_file, "w") as f:
            yaml.dump(users, f, default_flow_style=False)

    def register(self, username: str, password: str, email: str, display_name: str) -> bool:
        """Register a new user. Returns True on success."""
        users = self._load_users()

        if username in users:
            return False

        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        users[username] = {
            "password_hash": password_hash,
            "email": email,
            "display_name": display_name,
            "created_at": time.time(),
        }

        self._save_users(users)
        return True

    def authenticate(self, username: str, password: str) -> User | None:
        """Authenticate user credentials. Returns User on success."""
        users = self._load_users()

        if username not in users:
            return None

        user_data = users[username]
        stored_hash = user_data["password_hash"].encode("utf-8")

        if bcrypt.checkpw(password.encode("utf-8"), stored_hash):
            return User(
                username=username,
                email=user_data["email"],
                display_name=user_data["display_name"],
                created_at=user_data.get("created_at", 0),
            )
        return None

    def create_session(self, username: str) -> Session:
        """Create a new session for a user."""
        session_id = secrets.token_hex(16)
        session = Session(
            session_id=session_id,
            username=username,
        )
        self.save_session(session)
        return session

    def save_session(self, session: Session):
        """Persist session data to disk."""
        user_sessions_dir = self.sessions_dir / session.username
        user_sessions_dir.mkdir(parents=True, exist_ok=True)

        session_file = user_sessions_dir / f"{session.session_id}.json"
        data = {
            "session_id": session.session_id,
            "username": session.username,
            "created_at": session.created_at,
            "last_active": session.last_active,
            "agent_id": session.agent_id,
            "title": session.title,
            "acp_session_ids": session.acp_session_ids,
        }
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_session(self, username: str, session_id: str) -> Session | None:
        """Load a session from disk."""
        session_file = self.sessions_dir / username / f"{session_id}.json"
        if not session_file.exists():
            return None

        try:
            with open(session_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Session(
                session_id=data["session_id"],
                username=data["username"],
                created_at=data.get("created_at", 0),
                last_active=data.get("last_active", 0),
                agent_id=data.get("agent_id", ""),
                title=data.get("title", ""),
                acp_session_ids=data.get("acp_session_ids", {}),
            )
        except (json.JSONDecodeError, OSError, KeyError):
            return None

    def list_sessions(self, username: str) -> list[Session]:
        """List all sessions for a user, sorted by last_active (newest first)."""
        user_sessions_dir = self.sessions_dir / username
        if not user_sessions_dir.exists():
            return []

        sessions = []
        for session_file in user_sessions_dir.glob("*.json"):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                sessions.append(Session(
                    session_id=data["session_id"],
                    username=data["username"],
                    created_at=data.get("created_at", 0),
                    last_active=data.get("last_active", 0),
                    agent_id=data.get("agent_id", ""),
                    title=data.get("title", ""),
                    acp_session_ids=data.get("acp_session_ids", {}),
                ))
            except (json.JSONDecodeError, OSError, KeyError):
                continue

        # Sort by last_active, newest first
        sessions.sort(key=lambda s: s.created_at, reverse=True)
        return sessions

    def delete_session(self, username: str, session_id: str) -> bool:
        """Delete a session file."""
        session_file = self.sessions_dir / username / f"{session_id}.json"
        if session_file.exists():
            session_file.unlink()
            return True
        return False

    def generate_session_token(self, username: str) -> str:
        """Generate a unique session token."""
        raw = f"{username}-{time.time()}-{secrets.token_hex(8)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]
