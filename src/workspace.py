"""Workspace management for isolated user environments."""

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import git

from src.config import config


@dataclass
class Workspace:
    """Represents an isolated user workspace."""

    workspace_id: str
    username: str
    path: Path
    repos: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    @property
    def exists(self) -> bool:
        return self.path.exists()


class WorkspaceManager:
    """Manages per-user isolated workspaces."""

    def __init__(self, workspaces_root: Path | None = None):
        self.root = workspaces_root or config.workspaces_root
        self.root.mkdir(parents=True, exist_ok=True)

    def get_user_workspace_dir(self, username: str) -> Path:
        """Get the base workspace directory for a user."""
        return self.root / username

    def create_workspace(self, username: str, session_id: str) -> Workspace:
        """Create a new isolated workspace for a user session."""
        workspace_dir = self.get_user_workspace_dir(username) / session_id
        workspace_dir.mkdir(parents=True, exist_ok=True)

        workspace = Workspace(
            workspace_id=session_id,
            username=username,
            path=workspace_dir,
        )
        return workspace

    def get_workspace(self, username: str, session_id: str) -> Workspace | None:
        """Get an existing workspace."""
        workspace_dir = self.get_user_workspace_dir(username) / session_id
        if workspace_dir.exists():
            return Workspace(
                workspace_id=session_id,
                username=username,
                path=workspace_dir,
            )
        return None

    def list_workspaces(self, username: str) -> list[Workspace]:
        """List all workspaces for a user."""
        user_dir = self.get_user_workspace_dir(username)
        if not user_dir.exists():
            return []

        workspaces = []
        for ws_dir in user_dir.iterdir():
            if ws_dir.is_dir():
                workspaces.append(
                    Workspace(
                        workspace_id=ws_dir.name,
                        username=username,
                        path=ws_dir,
                    )
                )
        return workspaces

    def clone_repo(self, workspace: Workspace, repo_url: str, branch: str = "main") -> Path:
        """Clone a GitHub repository into the workspace."""
        # Extract repo name from URL
        repo_name = repo_url.rstrip("/").split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]

        repo_path = workspace.path / repo_name

        if repo_path.exists():
            # Pull latest if already cloned
            repo = git.Repo(repo_path)
            origin = repo.remotes.origin
            origin.pull(branch)
        else:
            # Fresh clone
            git.Repo.clone_from(
                repo_url,
                repo_path,
                branch=branch,
                depth=1,
            )

        if repo_name not in workspace.repos:
            workspace.repos.append(repo_name)

        return repo_path

    def delete_workspace(self, username: str, session_id: str) -> bool:
        """Delete a workspace and all its contents."""
        workspace_dir = self.get_user_workspace_dir(username) / session_id
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)
            return True
        return False

    def cleanup_old_workspaces(self, username: str, max_age_hours: int = 24):
        """Remove workspaces older than max_age_hours."""
        user_dir = self.get_user_workspace_dir(username)
        if not user_dir.exists():
            return

        cutoff = time.time() - (max_age_hours * 3600)
        for ws_dir in user_dir.iterdir():
            if ws_dir.is_dir() and ws_dir.stat().st_mtime < cutoff:
                shutil.rmtree(ws_dir)
