"""Kiro CLI ACP (Agent Client Protocol) client.

Each user gets a persistent ACP process + session for the lifetime of their
UI session window. Prompts are dispatched via asyncio.Queue to a background
event loop running in a dedicated thread.
"""

import asyncio
import logging
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from src.config import config

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
    role: str  # "user" or "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


# One background event loop shared across all users
_bg_loop: asyncio.AbstractEventLoop | None = None
_bg_loop_lock = threading.Lock()


def _get_bg_loop() -> asyncio.AbstractEventLoop:
    global _bg_loop
    with _bg_loop_lock:
        if _bg_loop is None or _bg_loop.is_closed():
            _bg_loop = asyncio.new_event_loop()
            t = threading.Thread(target=_bg_loop.run_forever, daemon=True)
            t.start()
        return _bg_loop


def _resolve_kiro_path() -> str:
    path = shutil.which(config.kiro_cli_path)
    if not path:
        local_bin = Path.home() / ".local" / "bin" / config.kiro_cli_path
        path = str(local_bin) if local_bin.is_file() else None
    if not path:
        raise FileNotFoundError(
            f"'{config.kiro_cli_path}' not found. Install Kiro CLI: https://kiro.dev/cli/"
        )
    return path


IDLE_TIMEOUT_SECONDS = 30 * 60  # 30 minutes


class _PromptRequest:
    def __init__(self, message: str):
        self.message = message
        self.future: asyncio.Future = None  # set by the worker


class _UserSession:
    """Holds the persistent ACP process and session for one user."""

    def __init__(self, username: str, workspace_path: Path, agent_id: str = "",
                 acp_session_id: str = "", on_session_created=None):
        self.username = username
        self.workspace_path = workspace_path
        self.agent_id = agent_id
        self.acp_session_id = acp_session_id  # kiro-cli session id to resume
        self.on_session_created = on_session_created  # callback(agent_id, session_id)
        self.status = AgentStatus.STOPPED
        self.messages: list[AgentMessage] = []
        self._queue: asyncio.Queue = None
        self._conn = None       # live ACP connection
        self._acp_sid: str = "" # active kiro session id
        self._queue_ready = threading.Event()
        self._task: asyncio.Task = None

    def start(self, loop: asyncio.AbstractEventLoop):
        # Queue must be created inside the bg loop
        future = asyncio.run_coroutine_threadsafe(self._init_and_run(), loop)
        self._bg_future = future

    async def _init_and_run(self):
        self._queue = asyncio.Queue()
        self._queue_ready.set()
        await self._run()

    async def _run(self):
        import acp

        collected: list[str] = []
        current_future: asyncio.Future | None = None

        class Client:
            async def request_permission(self, **kwargs):
                opts = kwargs.get("options", [{}])
                return {"optionId": opts[0].get("id", "allow") if opts else "allow"}

            async def session_update(self, session_id, update, **kwargs):
                if hasattr(update, "content") and hasattr(update.content, "text"):
                    collected.append(update.content.text)

            async def write_text_file(self, **kwargs):
                return None

            async def read_text_file(self, path, session_id, **kwargs):
                try:
                    return {"content": Path(path).read_text()}
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

        kiro_path = _resolve_kiro_path()
        self.status = AgentStatus.INITIALIZING

        args = ["acp"]
        if self.agent_id:
            args += ["--agent", self.agent_id]

        try:
            async with acp.spawn_agent_process(
                Client(),
                kiro_path,
                *args,
                cwd=str(self.workspace_path),
            ) as (conn, process):
                logger.info(f"ACP process spawned (PID {process.pid})")

                await conn.initialize(
                    protocol_version=acp.PROTOCOL_VERSION,
                    client_info={"name": "kiro-web-like", "version": "0.1.0"},
                )
                logger.info(f"ACP initialized for {self.username}")

                if self.acp_session_id:
                    await conn.load_session(cwd=str(self.workspace_path), session_id=self.acp_session_id)
                    session_id = self.acp_session_id
                    logger.info(f"ACP session loaded: {session_id}")
                else:
                    session_resp = await conn.new_session(cwd=str(self.workspace_path))
                    session_id = session_resp.session_id
                    logger.info(f"ACP session created: {session_id}")
                    if self.on_session_created:
                        self.on_session_created(self.agent_id, session_id)
                self._conn = conn
                self._acp_sid = session_id
                self.status = AgentStatus.IDLE

                # Process prompts until queue receives None (shutdown signal) or idle timeout
                while True:
                    try:
                        req: _PromptRequest | None = await asyncio.wait_for(
                            self._queue.get(), timeout=IDLE_TIMEOUT_SECONDS
                        )
                    except asyncio.TimeoutError:
                        logger.info(f"ACP session idle timeout for {self.username}, shutting down")
                        self.status = AgentStatus.STOPPED
                        break
                    if req is None:
                        break

                    self.status = AgentStatus.RUNNING
                    collected.clear()
                    try:
                        await conn.prompt(
                            prompt=[acp.text_block(req.message)],
                            session_id=session_id,
                        )
                        logger.info("Prompt completed")
                        result = "".join(collected) or "*(no output)*"
                        req.future.set_result(result)
                    except Exception as e:
                        req.future.set_exception(e)
                    finally:
                        self.status = AgentStatus.IDLE

        except Exception as e:
            self.status = AgentStatus.ERROR
            logger.error(f"ACP session error for {self.username}: {e}")
            # Fail any pending request
            try:
                req = self._queue.get_nowait()
                if req and req.future and not req.future.done():
                    req.future.set_exception(e)
            except asyncio.QueueEmpty:
                pass
            raise

    def prompt(self, message: str, loop: asyncio.AbstractEventLoop) -> str:
        self._queue_ready.wait(timeout=30)  # wait for ACP process to initialize
        req = _PromptRequest(message)
        req.future = loop.create_future()
        asyncio.run_coroutine_threadsafe(self._queue.put(req), loop)
        # Bridge asyncio.Future → concurrent.futures.Future so we can block here
        import concurrent.futures
        cf = concurrent.futures.Future()
        def _on_done(f):
            if f.exception():
                cf.set_exception(f.exception())
            else:
                cf.set_result(f.result())
        loop.call_soon_threadsafe(req.future.add_done_callback, _on_done)
        return cf.result(timeout=300)

    def cancel(self, loop: asyncio.AbstractEventLoop):
        """Send session/cancel notification to kiro-cli."""
        if self._conn and self._acp_sid:
            asyncio.run_coroutine_threadsafe(
                self._conn.cancel(session_id=self._acp_sid), loop
            )

    def stop(self, loop: asyncio.AbstractEventLoop):
        if self._queue:
            asyncio.run_coroutine_threadsafe(self._queue.put(None), loop)
        self.status = AgentStatus.STOPPED


class ACPClient:
    """Manages persistent per-user ACP sessions."""

    def __init__(self):
        self._sessions: dict[str, _UserSession] = {}
        self._lock = threading.Lock()

    def _session_key(self, username: str, agent_id: str, session_id: str = "") -> str:
        return f"{username}:{agent_id}:{session_id}"

    def _get_or_create_session(self, username: str, workspace_path: Path, agent_id: str, session_id: str) -> _UserSession:
        key = self._session_key(username, agent_id, session_id)
        with self._lock:
            session = self._sessions.get(key)
            if session and session.status not in (AgentStatus.STOPPED, AgentStatus.ERROR):
                return session
            # Look up persisted kiro-cli session id from app session
            from src.auth import AuthManager
            auth = AuthManager()
            app_session = auth.load_session(username, session_id)
            acp_sid = app_session.acp_session_ids.get(agent_id, "") if app_session else ""

            def _on_created(aid, new_acp_sid):
                s = auth.load_session(username, session_id)
                if s:
                    s.acp_session_ids[aid] = new_acp_sid
                    auth.save_session(s)
                    logger.info(f"Saved acp_session_id {new_acp_sid} for session {session_id} agent {aid}")

            session = _UserSession(username, workspace_path, agent_id,
                                   acp_session_id=acp_sid, on_session_created=_on_created)
            self._sessions[key] = session

        loop = _get_bg_loop()
        session.start(loop)
        return session

    def prompt(self, username: str, workspace_path: Path, message: str, agent_id: str = "", session_id: str = "") -> str:
        session = self._get_or_create_session(username, workspace_path, agent_id, session_id)
        session.messages.append(AgentMessage(role="user", content=message))
        try:
            response = session.prompt(message, _get_bg_loop())
            session.messages.append(AgentMessage(role="assistant", content=response))
            return response
        except Exception as e:
            session.status = AgentStatus.ERROR
            logger.error(f"ACP prompt failed for {username}: {e}")
            raise

    def get_status(self, username: str, agent_id: str = "", session_id: str = "") -> AgentStatus:
        key = self._session_key(username, agent_id, session_id)
        with self._lock:
            session = self._sessions.get(key)
        return session.status if session else AgentStatus.STOPPED

    def get_messages(self, username: str, agent_id: str = "", session_id: str = "") -> list[AgentMessage]:
        key = self._session_key(username, agent_id, session_id)
        with self._lock:
            session = self._sessions.get(key)
        return session.messages if session else []

    def cancel(self, username: str, agent_id: str = "", session_id: str = ""):
        key = self._session_key(username, agent_id, session_id)
        with self._lock:
            session = self._sessions.get(key)
        if session:
            session.cancel(_get_bg_loop())

    def disconnect(self, username: str, agent_id: str | None = None, session_id: str | None = None):
        """Disconnect a specific agent session, or all sessions for a user."""
        loop = _get_bg_loop()
        with self._lock:
            if agent_id is not None and session_id is not None:
                keys = [self._session_key(username, agent_id, session_id)]
            else:
                keys = [k for k in self._sessions if k.startswith(f"{username}:")]
            sessions = {k: self._sessions.pop(k) for k in keys if k in self._sessions}
        for s in sessions.values():
            s.stop(loop)

    def get_connection(self, username: str, agent_id: str = "", session_id: str = ""):
        key = self._session_key(username, agent_id, session_id)
        with self._lock:
            return self._sessions.get(key)

    def close_session(self, conn):
        pass


acp_client = ACPClient()
