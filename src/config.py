"""Application configuration management."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Application-wide configuration."""

    # Kiro CLI
    kiro_api_key: str = field(default_factory=lambda: os.getenv("KIRO_API_KEY", ""))
    kiro_cli_path: str = field(default_factory=lambda: os.getenv("KIRO_CLI_PATH", "kiro-cli"))

    # Paths
    workspaces_root: Path = field(
        default_factory=lambda: Path(os.getenv("WORKSPACES_ROOT", "/tmp/kiro-workspaces"))
    )
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "./data")))

    # App
    app_secret_key: str = field(
        default_factory=lambda: os.getenv("APP_SECRET_KEY", "change-me-in-production")
    )
    max_sessions_per_user: int = 5
    session_timeout_minutes: int = 60

    def __post_init__(self):
        """Ensure required directories exist."""
        self.workspaces_root.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)


# Global config instance
config = Config()
