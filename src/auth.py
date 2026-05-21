"""User authentication and session management."""

import hashlib
import secrets
import time
from dataclasses import dataclass, field
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
    mode: str = "vibe"  # "vibe" or "autonomous"
    repos: list = field(default_factory=list)


class AuthManager:
    """Manages user registration, login, and sessions."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or config.data_dir
        self.users_file = self.data_dir / "users.yaml"
        self._ensure_users_file()

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

    def create_session(self, username: str, mode: str = "vibe") -> Session:
        """Create a new session for a user."""
        session_id = secrets.token_hex(16)
        return Session(
            session_id=session_id,
            username=username,
            mode=mode,
        )

    def generate_session_token(self, username: str) -> str:
        """Generate a unique session token."""
        raw = f"{username}-{time.time()}-{secrets.token_hex(8)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]
