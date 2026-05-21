"""Kiro CLI agent process manager.

Manages spawning, communication, and lifecycle of Kiro CLI headless processes
for each user session.
"""

import asyncio
import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from queue import Queue

import psutil

from src.config import config


class AgentMode(str, Enum):
    VIBE = "vibe"
    AUTONOMOUS = "autonomous"


class AgentStatus(str, Enum):
    IDLE = "idle"
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
class AgentProcess:
    """Tracks a running Kiro CLI agent process."""

    process_id: str
    username: str
    session_id: str
    workspace_path: Path
    mode: AgentMode
    status: AgentStatus = AgentStatus.IDLE
    pid: int | None = None
    messages: list[AgentMessage] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    _process: subprocess.Popen | None = field(default=None, repr=False)
    _output_queue: Queue = field(default_factory=Queue, repr=False)
    _reader_thread: threading.Thread | None = field(default=None, repr=False)


class AgentManager:
    """Manages Kiro CLI agent processes for all user sessions."""

    def __init__(self):
        self._processes: dict[str, AgentProcess] = {}
        self._lock = threading.Lock()

    def _build_kiro_command(
        self,
        prompt: str,
        workspace_path: Path,
        mode: AgentMode,
        trust_all_tools: bool = True,
    ) -> list[str]:
        """Build the kiro CLI command for headless execution."""
        cmd = [
            config.kiro_cli_path,
            "--no-interactive",
        ]

        if trust_all_tools:
            cmd.append("--trust-all-tools")

        # Add prompt
        cmd.extend(["--prompt", prompt])

        return cmd

    def _get_env(self) -> dict:
        """Get environment variables for the Kiro process."""
        env = os.environ.copy()
        env["KIRO_API_KEY"] = config.kiro_api_key
        # Disable any interactive features
        env["TERM"] = "dumb"
        env["NO_COLOR"] = "1"
        return env

    def _read_output(self, agent: AgentProcess):
        """Background thread to read process stdout."""
        if agent._process and agent._process.stdout:
            try:
                for line in iter(agent._process.stdout.readline, ""):
                    if line:
                        agent._output_queue.put(line.rstrip("\n"))
                    if agent._process.poll() is not None:
                        break
            except (ValueError, OSError):
                pass  # Process closed

    def start_agent(
        self,
        username: str,
        session_id: str,
        workspace_path: Path,
        prompt: str,
        mode: AgentMode = AgentMode.VIBE,
    ) -> AgentProcess:
        """Start a new Kiro CLI agent process for a user session."""
        process_id = f"{username}-{session_id}"

        # Stop existing process if any
        if process_id in self._processes:
            self.stop_agent(process_id)

        cmd = self._build_kiro_command(prompt, workspace_path, mode)
        env = self._get_env()

        try:
            # Verify kiro CLI exists before spawning
            import shutil
            kiro_path = shutil.which(config.kiro_cli_path)
            if not kiro_path:
                raise FileNotFoundError(
                    f"'{config.kiro_cli_path}' not found in PATH. "
                    f"PATH={env.get('PATH', 'not set')}"
                )

            process = subprocess.Popen(
                cmd,
                cwd=str(workspace_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                env=env,
                bufsize=1,
            )

            agent = AgentProcess(
                process_id=process_id,
                username=username,
                session_id=session_id,
                workspace_path=workspace_path,
                mode=mode,
                status=AgentStatus.RUNNING,
                pid=process.pid,
                _process=process,
            )

            # Add the user message
            agent.messages.append(AgentMessage(role="user", content=prompt))

            # Start output reader thread
            reader = threading.Thread(target=self._read_output, args=(agent,), daemon=True)
            reader.start()
            agent._reader_thread = reader

            with self._lock:
                self._processes[process_id] = agent

            return agent

        except FileNotFoundError as e:
            agent = AgentProcess(
                process_id=process_id,
                username=username,
                session_id=session_id,
                workspace_path=workspace_path,
                mode=mode,
                status=AgentStatus.ERROR,
            )
            agent.messages.append(
                AgentMessage(
                    role="assistant",
                    content=f"Error: Kiro CLI not found.\n\nDetails: {e}\n\n"
                    f"Please ensure 'kiro' is installed and available in PATH.\n"
                    f"Set KIRO_CLI_PATH in .env if it's in a custom location.",
                )
            )
            with self._lock:
                self._processes[process_id] = agent
            return agent

        except PermissionError as e:
            agent = AgentProcess(
                process_id=process_id,
                username=username,
                session_id=session_id,
                workspace_path=workspace_path,
                mode=mode,
                status=AgentStatus.ERROR,
            )
            agent.messages.append(
                AgentMessage(
                    role="assistant",
                    content=f"Error: Permission denied when running Kiro CLI.\n\nDetails: {e}\n\n"
                    f"Try: `chmod +x $(which kiro)`",
                )
            )
            with self._lock:
                self._processes[process_id] = agent
            return agent

        except Exception as e:
            agent = AgentProcess(
                process_id=process_id,
                username=username,
                session_id=session_id,
                workspace_path=workspace_path,
                mode=mode,
                status=AgentStatus.ERROR,
            )
            agent.messages.append(
                AgentMessage(
                    role="assistant",
                    content=f"Error starting Kiro CLI agent.\n\nDetails: {type(e).__name__}: {e}\n\n"
                    f"Command: `{' '.join(cmd)}`\n"
                    f"Workspace: `{workspace_path}`",
                )
            )
            with self._lock:
                self._processes[process_id] = agent
            return agent

    def send_message(self, process_id: str, message: str) -> bool:
        """Send a message/prompt to a running agent process via stdin."""
        with self._lock:
            agent = self._processes.get(process_id)

        if not agent or not agent._process or agent._process.poll() is not None:
            return False

        try:
            agent._process.stdin.write(message + "\n")
            agent._process.stdin.flush()
            agent.messages.append(AgentMessage(role="user", content=message))
            return True
        except (OSError, BrokenPipeError):
            agent.status = AgentStatus.ERROR
            return False

    def get_output(self, process_id: str) -> list[str]:
        """Get any new output from the agent process."""
        with self._lock:
            agent = self._processes.get(process_id)

        if not agent:
            return []

        lines = []
        while not agent._output_queue.empty():
            try:
                lines.append(agent._output_queue.get_nowait())
            except Exception:
                break

        # Check if process has finished
        if agent._process and agent._process.poll() is not None:
            agent.status = AgentStatus.STOPPED

        # Combine output into assistant message
        if lines:
            combined = "\n".join(lines)
            agent.messages.append(AgentMessage(role="assistant", content=combined))

        return lines

    def get_status(self, process_id: str) -> AgentStatus:
        """Get the current status of an agent process."""
        with self._lock:
            agent = self._processes.get(process_id)

        if not agent:
            return AgentStatus.STOPPED

        if agent._process and agent._process.poll() is not None:
            agent.status = AgentStatus.STOPPED

        return agent.status

    def get_messages(self, process_id: str) -> list[AgentMessage]:
        """Get all messages for an agent process."""
        with self._lock:
            agent = self._processes.get(process_id)
        return agent.messages if agent else []

    def stop_agent(self, process_id: str) -> bool:
        """Stop a running agent process."""
        with self._lock:
            agent = self._processes.get(process_id)

        if not agent or not agent._process:
            return False

        try:
            # Try graceful shutdown first
            agent._process.terminate()
            try:
                agent._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                agent._process.kill()
                agent._process.wait(timeout=3)

            agent.status = AgentStatus.STOPPED
            return True
        except (OSError, psutil.Error):
            agent.status = AgentStatus.ERROR
            return False

    def cleanup_user_processes(self, username: str):
        """Stop all processes for a user."""
        with self._lock:
            user_processes = [
                pid for pid, agent in self._processes.items() if agent.username == username
            ]

        for pid in user_processes:
            self.stop_agent(pid)

    def list_user_processes(self, username: str) -> list[AgentProcess]:
        """List all agent processes for a user."""
        with self._lock:
            return [
                agent for agent in self._processes.values() if agent.username == username
            ]


# Global agent manager instance
agent_manager = AgentManager()
