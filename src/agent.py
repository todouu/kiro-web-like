"""Kiro CLI ACP (Agent Client Protocol) client.

Uses JSON-RPC 2.0 over stdin/stdout to communicate with `kiro-cli acp`,
enabling persistent multi-turn conversations within a session.

ACP lifecycle:
    initialize → session/new → session/prompt (repeatable) → session/close
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from src.config import config

# Configure logging to output to stderr (visible in streamlit terminal)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


class AgentMode(str, Enum):
    VIBE = "vibe"
    AUTONOMOUS = "autonomous"


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
class ACPConnection:
    """Represents a live connection to a kiro-cli acp process."""

    process: subprocess.Popen
    username: str
    workspace_path: Path
    session_id: str | None = None  # ACP session ID (from session/new response)
    status: AgentStatus = AgentStatus.INITIALIZING
    messages: list[AgentMessage] = field(default_factory=list)
    _request_id: int = field(default=0, repr=False)
    _response_queue: Queue = field(default_factory=Queue, repr=False)
    _notification_queue: Queue = field(default_factory=Queue, repr=False)
    _reader_thread: threading.Thread | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    created_at: float = field(default_factory=time.time)

    def next_id(self) -> int:
        with self._lock:
            self._request_id += 1
            return self._request_id


class ACPClient:
    """
    Manages Kiro CLI ACP processes.

    Each user gets a persistent `kiro-cli acp` subprocess.
    Multiple conversation sessions can be created within one process.
    """

    def __init__(self):
        self._connections: dict[str, ACPConnection] = {}  # key: username
        self._lock = threading.Lock()

    def _get_env(self) -> dict:
        """Environment variables for the kiro-cli acp process."""
        env = os.environ.copy()
        env["KIRO_API_KEY"] = config.kiro_api_key
        env["TERM"] = "dumb"
        env["NO_COLOR"] = "1"
        return env

    def _reader_loop(self, conn: ACPConnection):
        """Background thread: read newline-delimited JSON-RPC messages from stdout."""
        try:
            for raw_line in iter(conn.process.stdout.readline, ""):
                line = raw_line.strip()
                if not line:
                    continue

                logger.debug(f"ACP stdout: {line[:200]}")

                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(f"Non-JSON output from kiro-cli acp: {line[:200]}")
                    continue

                # JSON-RPC response (has "id")
                if "id" in msg and ("result" in msg or "error" in msg):
                    conn._response_queue.put(msg)
                # JSON-RPC notification (no "id", has "method")
                elif "method" in msg:
                    conn._notification_queue.put(msg)
                else:
                    logger.debug(f"Unknown ACP message: {msg}")

        except (ValueError, OSError) as e:
            logger.warning(f"ACP reader loop ended: {e}")
        finally:
            conn.status = AgentStatus.STOPPED
            logger.info(f"ACP reader loop finished for {conn.username}")

    def _stderr_loop(self, conn: ACPConnection):
        """Background thread: read stderr from the ACP process and log it."""
        try:
            if conn.process.stderr:
                for line in iter(conn.process.stderr.readline, ""):
                    if line.strip():
                        logger.info(f"ACP stderr [{conn.username}]: {line.rstrip()}")
        except (ValueError, OSError):
            pass

    def _send_request(self, conn: ACPConnection, method: str, params: dict | None = None) -> dict:
        """Send a JSON-RPC request and wait for the response."""
        request_id = conn.next_id()
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        raw = json.dumps(request) + "\n"

        try:
            conn.process.stdin.write(raw)
            conn.process.stdin.flush()
        except (OSError, BrokenPipeError) as e:
            conn.status = AgentStatus.ERROR
            raise ConnectionError(f"Failed to send to kiro-cli acp: {e}")

        # Wait for matching response (timeout 120s)
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                resp = conn._response_queue.get(timeout=1.0)
                if resp.get("id") == request_id:
                    if "error" in resp:
                        raise RuntimeError(
                            f"ACP error ({resp['error'].get('code', '?')}): "
                            f"{resp['error'].get('message', 'unknown')}"
                        )
                    return resp.get("result", {})
                else:
                    # Not our response — put it back (rare edge case)
                    conn._response_queue.put(resp)
            except Empty:
                # Check if process died
                if conn.process.poll() is not None:
                    conn.status = AgentStatus.ERROR
                    raise ConnectionError(
                        f"kiro-cli acp process exited with code {conn.process.returncode}"
                    )
                continue

        raise TimeoutError("Timed out waiting for ACP response")

    def _send_notification(self, conn: ACPConnection, method: str, params: dict | None = None):
        """Send a JSON-RPC notification (no response expected)."""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            notification["params"] = params

        raw = json.dumps(notification) + "\n"
        try:
            conn.process.stdin.write(raw)
            conn.process.stdin.flush()
        except (OSError, BrokenPipeError):
            pass

    def _collect_streaming_response(self, conn: ACPConnection, timeout: float = 120) -> str:
        """
        After sending session/prompt, collect streaming session/update notifications
        until we get a prompt_done event or timeout.
        """
        output_parts = []
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                notification = conn._notification_queue.get(timeout=1.0)
                method = notification.get("method", "")
                params = notification.get("params", {})

                if method == "session/update":
                    # Extract text content from the update
                    content_blocks = params.get("content", [])
                    for block in content_blocks:
                        if block.get("type") == "text":
                            output_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tool_name = block.get("name", "unknown")
                            output_parts.append(f"\n🔧 *Using tool: {tool_name}*\n")
                        elif block.get("type") == "tool_result":
                            pass  # Usually internal

                    # Check if this is the end of the turn
                    if params.get("done") or params.get("event") == "prompt_done":
                        break

                elif method == "session/event":
                    event_type = params.get("event", "")
                    if event_type in ("prompt_done", "end_turn"):
                        break

            except Empty:
                # Check if process died
                if conn.process.poll() is not None:
                    break
                continue

        # Also check response queue for the prompt response
        try:
            resp = conn._response_queue.get_nowait()
            if "result" in resp:
                result = resp["result"]
                content_blocks = result.get("content", [])
                for block in content_blocks:
                    if block.get("type") == "text":
                        output_parts.append(block.get("text", ""))
        except Empty:
            pass

        return "".join(output_parts)

    def connect(self, username: str, workspace_path: Path) -> ACPConnection:
        """
        Start a kiro-cli acp process for a user and perform initialization.
        Reuses existing connection if alive.
        """
        with self._lock:
            existing = self._connections.get(username)
            if existing and existing.process.poll() is None:
                return existing

        # Verify kiro CLI exists
        kiro_path = shutil.which(config.kiro_cli_path)
        if not kiro_path:
            raise FileNotFoundError(
                f"'{config.kiro_cli_path}' not found in PATH. "
                f"Install Kiro CLI: https://kiro.dev/cli/"
            )

        cmd = [config.kiro_cli_path, "acp"]
        env = self._get_env()

        logger.info(f"Starting ACP process: {' '.join(cmd)}")
        logger.info(f"Working directory: {workspace_path}")
        logger.info(f"KIRO_API_KEY set: {'yes' if env.get('KIRO_API_KEY') else 'NO'}")

        try:
            process = subprocess.Popen(
                cmd,
                cwd=str(workspace_path),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=env,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to start kiro-cli acp: {e}")

        conn = ACPConnection(
            process=process,
            username=username,
            workspace_path=workspace_path,
        )

        # Start reader thread
        reader = threading.Thread(target=self._reader_loop, args=(conn,), daemon=True)
        reader.start()
        conn._reader_thread = reader

        # Start stderr reader thread for logging
        stderr_reader = threading.Thread(
            target=self._stderr_loop, args=(conn,), daemon=True
        )
        stderr_reader.start()

        # Give the process a moment to start
        time.sleep(1.0)

        # Check if process died immediately
        if process.poll() is not None:
            stderr_output = process.stderr.read() if process.stderr else ""
            logger.error(
                f"kiro-cli acp exited immediately (code {process.returncode}). "
                f"stderr: {stderr_output[:1000]}"
            )
            raise RuntimeError(
                f"kiro-cli acp exited immediately (code {process.returncode}).\n"
                f"stderr: {stderr_output[:500]}\n\n"
                f"Command: {' '.join(cmd)}\n"
                f"Try running manually: KIRO_API_KEY=xxx kiro-cli acp"
            )

        logger.info(f"ACP process started (PID {process.pid}), sending initialize...")

        # Send initialize handshake
        try:
            init_result = self._send_request(conn, "initialize", {
                "protocolVersion": "0.1",
                "clientInfo": {
                    "name": "kiro-web-like",
                    "version": "0.1.0",
                },
                "capabilities": {},
            })
            logger.info(f"ACP initialized for {username}: {init_result}")
            conn.status = AgentStatus.IDLE
        except Exception as e:
            # Try to read stderr for more info
            stderr_output = ""
            try:
                if process.stderr:
                    stderr_output = process.stderr.read()
            except Exception:
                pass
            logger.error(f"ACP initialization failed: {e}. stderr: {stderr_output[:500]}")
            self._kill(conn)
            raise RuntimeError(
                f"ACP initialization failed: {e}\n"
                f"stderr: {stderr_output[:500]}"
            )

        with self._lock:
            self._connections[username] = conn

        return conn

    def new_session(self, conn: ACPConnection) -> str:
        """Create a new ACP conversation session. Returns session_id."""
        result = self._send_request(conn, "session/new", {
            "workspace": str(conn.workspace_path),
        })
        session_id = result.get("sessionId", result.get("session_id", ""))
        conn.session_id = session_id
        conn.messages = []
        logger.info(f"New ACP session: {session_id}")
        return session_id

    def prompt(self, conn: ACPConnection, message: str) -> str:
        """
        Send a user prompt within the current session.
        Returns the agent's response text.
        Multi-turn context is maintained by the ACP server automatically.
        """
        if not conn.session_id:
            self.new_session(conn)

        conn.status = AgentStatus.RUNNING
        conn.messages.append(AgentMessage(role="user", content=message))

        # Send session/prompt request
        request_id = conn.next_id()
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "session/prompt",
            "params": {
                "sessionId": conn.session_id,
                "content": [
                    {"type": "text", "text": message}
                ],
            },
        }

        raw = json.dumps(request) + "\n"
        try:
            conn.process.stdin.write(raw)
            conn.process.stdin.flush()
        except (OSError, BrokenPipeError) as e:
            conn.status = AgentStatus.ERROR
            raise ConnectionError(f"Failed to send prompt: {e}")

        # Collect streaming response
        response_text = self._collect_streaming_response(conn, timeout=180)

        # Also try to get the final RPC response
        try:
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    resp = conn._response_queue.get(timeout=1.0)
                    if resp.get("id") == request_id:
                        if "error" in resp:
                            error_msg = resp["error"].get("message", "Unknown error")
                            conn.status = AgentStatus.IDLE
                            return f"❌ Agent error: {error_msg}"
                        # Extract content from final response if we didn't get it streaming
                        if not response_text and "result" in resp:
                            result = resp["result"]
                            content_blocks = result.get("content", [])
                            for block in content_blocks:
                                if block.get("type") == "text":
                                    response_text += block.get("text", "")
                        break
                    else:
                        conn._response_queue.put(resp)
                except Empty:
                    break
        except Exception:
            pass

        conn.status = AgentStatus.IDLE

        if not response_text:
            response_text = "*(Agent completed but produced no text output)*"

        conn.messages.append(AgentMessage(role="assistant", content=response_text))
        return response_text

    def close_session(self, conn: ACPConnection):
        """Close the current ACP session (but keep the process alive)."""
        if conn.session_id:
            try:
                self._send_notification(conn, "session/close", {
                    "sessionId": conn.session_id,
                })
            except Exception:
                pass
            conn.session_id = None
            conn.messages = []

    def disconnect(self, username: str):
        """Stop the ACP process for a user."""
        with self._lock:
            conn = self._connections.pop(username, None)
        if conn:
            self._kill(conn)

    def _kill(self, conn: ACPConnection):
        """Terminate an ACP process."""
        try:
            conn.process.terminate()
            try:
                conn.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                conn.process.kill()
                conn.process.wait(timeout=3)
        except (OSError, ProcessLookupError):
            pass
        conn.status = AgentStatus.STOPPED

    def get_connection(self, username: str) -> ACPConnection | None:
        """Get existing connection for a user."""
        with self._lock:
            conn = self._connections.get(username)
        if conn and conn.process.poll() is not None:
            conn.status = AgentStatus.STOPPED
            return None
        return conn

    def get_messages(self, username: str) -> list[AgentMessage]:
        """Get conversation history for a user's current session."""
        conn = self.get_connection(username)
        return conn.messages if conn else []

    def get_status(self, username: str) -> AgentStatus:
        """Get agent status for a user."""
        conn = self.get_connection(username)
        return conn.status if conn else AgentStatus.STOPPED


# Global ACP client instance
acp_client = ACPClient()
