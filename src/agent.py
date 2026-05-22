"""Kiro CLI ACP (Agent Client Protocol) client.

Uses the official `agent-client-protocol` Python SDK to communicate
with `kiro-cli acp` over stdin/stdout JSON-RPC.

Install: pip install agent-client-protocol

ACP lifecycle:
    initialize → new_session(cwd=...) → prompt(...) → close_session
"""

import asyncio
import logging
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from src.config import config

# Configure logging — only our module at INFO level
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False


class AgentStatus(str, Enum):
    IDLE = "idle"
    INITIALIZING = "initializing"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class AgentMessage:
    """A message in the agent conversation."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


@dataclass
class ACPSession:
    """Tracks a user's ACP session state."""

    username: str
    workspace_path: Path
    session_id: str | None = None
    status: AgentStatus = AgentStatus.STOPPED
    messages: list[AgentMessage] = field(default_factory=list)


class ACPClient:
    """
    Manages Kiro CLI ACP connections using the official SDK.

    Each user gets a persistent session with multi-turn context.
    """

    def __init__(self):
        self._sessions: dict[str, ACPSession] = {}
        self._lock = threading.Lock()

    def _get_event_loop(self):
        """Get or create an event loop for async operations."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop

    def _run_async(self, coro):
        """Run an async coroutine synchronously."""
        loop = self._get_event_loop()
        if loop.is_running():
            # If loop is already running (e.g. in Streamlit), use thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result()
        else:
            return loop.run_until_complete(coro)

    async def _connect_and_prompt(self, username: str, workspace_path: Path, message: str) -> str:
        """Connect to kiro-cli acp, create session, send prompt, return response."""
        import acp

        collected_text: list[str] = []

        class MyClient:
            """ACP Client that collects session updates."""

            async def request_permission(self, **kwargs):
                # Auto-approve all tool calls
                return {"optionId": kwargs.get("options", [{}])[0].get("id", "allow")}

            async def session_update(self, session_id, update, **kwargs):
                # Collect text from agent messages
                if hasattr(update, "text"):
                    collected_text.append(update.text)

            async def write_text_file(self, **kwargs):
                return None

            async def read_text_file(self, path, session_id, **kwargs):
                try:
                    content = Path(path).read_text()
                    return {"content": content}
                except Exception:
                    return {"content": ""}

            async def create_terminal(self, **kwargs):
                return {"terminalId": "stub"}

            async def terminal_output(self, **kwargs):
                return {"output": ""}

            async def release_terminal(self, **kwargs):
                return None

            async def wait_for_terminal_exit(self, **kwargs):
                return {"exitCode": 0}

            async def kill_terminal(self, **kwargs):
                return None

            async def ext_method(self, method, params):
                return {}

            async def ext_notification(self, method, params):
                pass

            def on_connect(self, conn):
                pass

        client = MyClient()
        kiro_path = shutil.which(config.kiro_cli_path)
        if not kiro_path:
            raise FileNotFoundError(
                f"'{config.kiro_cli_path}' not found in PATH. "
                f"Install Kiro CLI: https://kiro.dev/cli/"
            )

        logger.info(f"Connecting to kiro-cli acp for {username}, cwd={workspace_path}")

        async with acp.spawn_agent_process(
            client,
            config.kiro_cli_path,
            "acp",
            cwd=str(workspace_path),
        ) as (conn, process):
            logger.info(f"ACP process spawned (PID {process.pid})")

            # Initialize
            init_resp = await conn.initialize(
                protocol_version=acp.PROTOCOL_VERSION,
                client_info={"name": "kiro-web-like", "version": "0.1.0"},
            )
            logger.info(f"ACP initialized: {init_resp.agent_info}")

            # Create session with cwd parameter
            session_resp = await conn.new_session(cwd=str(workspace_path))
            session_id = session_resp.session_id
            logger.info(f"ACP session created: {session_id}")

            # Send prompt
            prompt_resp = await conn.prompt(
                prompt=[acp.text_block(message)],
                session_id=session_id,
            )
            logger.info(f"Prompt completed")

            # Extract response text from prompt response
            response_text = ""
            if prompt_resp and prompt_resp.content:
                for block in prompt_resp.content:
                    if hasattr(block, "text"):
                        response_text += block.text

            # Also include any streamed text
            if collected_text:
                streamed = "".join(collected_text)
                if streamed and not response_text:
                    response_text = streamed

        return response_text or "*(Agent completed but produced no text output)*"

    def prompt(self, username: str, workspace_path: Path, message: str) -> str:
        """
        Send a prompt to the Kiro CLI agent via ACP.

        Each call spawns a fresh ACP connection (the SDK handles the full lifecycle).
        Multi-turn context is managed via session persistence on the CLI side.
        """
        with self._lock:
            if username not in self._sessions:
                self._sessions[username] = ACPSession(
                    username=username,
                    workspace_path=workspace_path,
                )
            session = self._sessions[username]

        session.status = AgentStatus.RUNNING
        session.messages.append(AgentMessage(role="user", content=message))

        try:
            response = self._run_async(
                self._connect_and_prompt(username, workspace_path, message)
            )
            session.messages.append(AgentMessage(role="assistant", content=response))
            session.status = AgentStatus.IDLE
            return response
        except Exception as e:
            session.status = AgentStatus.ERROR
            logger.error(f"ACP prompt failed for {username}: {e}")
            raise

    def get_status(self, username: str) -> AgentStatus:
        """Get agent status for a user."""
        with self._lock:
            session = self._sessions.get(username)
        return session.status if session else AgentStatus.STOPPED

    def get_messages(self, username: str) -> list[AgentMessage]:
        """Get conversation history."""
        with self._lock:
            session = self._sessions.get(username)
        return session.messages if session else []

    def disconnect(self, username: str):
        """Clear session state for a user."""
        with self._lock:
            self._sessions.pop(username, None)

    def get_connection(self, username: str):
        """Compatibility method — returns session if exists."""
        with self._lock:
            return self._sessions.get(username)

    def close_session(self, conn):
        """Compatibility — clear messages."""
        if conn and hasattr(conn, "messages"):
            conn.messages = []


# Global ACP client instance
acp_client = ACPClient()
