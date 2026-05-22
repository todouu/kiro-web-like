"""
Kiro Web-Like: Main Streamlit Application

A browser-based interface for interacting with Kiro CLI agents via ACP
(Agent Client Protocol). Users select from pre-configured agents via a
dropdown below the chat, and chat within persistent multi-turn sessions.

Pages:
  - Chat (this file, main page)
  - Skills (pages/skills.py)
  - MCP (pages/mcp.py)
"""

import time

import streamlit as st

from src.agent import ACPClient, AgentStatus, acp_client
from src.agents_config import load_agents, get_agent
from src.auth import AuthManager
from src.config import config
from src.kiro_session import load_messages as load_kiro_messages
from src.workspace import WorkspaceManager

# --- Page Configuration ---
st.set_page_config(
    page_title="Kiro Web",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Custom CSS ---

# --- Initialize Services ---
auth_manager = AuthManager()
workspace_manager = WorkspaceManager()


def init_session_state():
    """Initialize all session state variables."""
    defaults = {
        "authenticated": False,
        "username": None,
        "user": None,
        "session": None,
        "workspace": None,
        "messages": [],
        "acp_connected": False,
        "selected_agent": None,
        "show_register": False,
        "agent_running": False,
        "pending_prompt": None,
        "pending_agent_id": None,
        "pending_agent_name": None,
        "agent_result": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()


# --- Authentication Pages ---
def render_login_page():
    """Render the login/register page."""
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.markdown("# 🤖 Kiro Web")
        st.markdown("*AI-powered development from your browser*")
        st.markdown("---")

        if st.session_state.show_register:
            render_register_form()
        else:
            render_login_form()


def render_login_form():
    """Render the login form."""
    st.subheader("Sign In")

    with st.form("login_form"):
        username = st.text_input("Username", placeholder="Enter your username")
        password = st.text_input("Password", type="password", placeholder="Enter your password")
        submit = st.form_submit_button("Sign In", use_container_width=True)

        if submit:
            if username and password:
                user = auth_manager.authenticate(username, password)
                if user:
                    session = auth_manager.create_session(username)
                    workspace = workspace_manager.create_workspace(username, session.session_id)

                    st.session_state.authenticated = True
                    st.session_state.username = username
                    st.session_state.user = user
                    st.session_state.session = session
                    st.session_state.workspace = workspace
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
            else:
                st.warning("Please enter both username and password.")

    st.markdown("---")
    if st.button("Don't have an account? Register", use_container_width=True):
        st.session_state.show_register = True
        st.rerun()


def render_register_form():
    """Render the registration form."""
    st.subheader("Create Account")

    with st.form("register_form"):
        display_name = st.text_input("Display Name", placeholder="Your name")
        email = st.text_input("Email", placeholder="you@example.com")
        username = st.text_input("Username", placeholder="Choose a username")
        password = st.text_input("Password", type="password", placeholder="Choose a password")
        password_confirm = st.text_input(
            "Confirm Password", type="password", placeholder="Confirm your password"
        )
        submit = st.form_submit_button("Create Account", use_container_width=True)

        if submit:
            if not all([display_name, email, username, password]):
                st.warning("Please fill in all fields.")
            elif password != password_confirm:
                st.error("Passwords do not match.")
            elif len(password) < 6:
                st.error("Password must be at least 6 characters.")
            else:
                success = auth_manager.register(username, password, email, display_name)
                if success:
                    st.success("Account created! Please sign in.")
                    st.session_state.show_register = False
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Username already taken.")

    st.markdown("---")
    if st.button("Already have an account? Sign In", use_container_width=True):
        st.session_state.show_register = False
        st.rerun()


# --- Main Application ---
def render_sidebar():
    """Render the application sidebar (agent + sessions + user at bottom)."""
    with st.sidebar:
        username = st.session_state.username

        workspace_path = None
        if st.session_state.workspace:
            workspace_path = st.session_state.workspace.path

        # Agent selector
        st.markdown("#### 🤖 AGENT")
        agents = load_agents(workspace_path)
        if agents:
            agent_ids = [a.id for a in agents]
            agent_labels = [a.name for a in agents]
            current_index = 0
            if st.session_state.selected_agent in agent_ids:
                current_index = agent_ids.index(st.session_state.selected_agent)
            selected_label = st.selectbox(
                "Agent", options=agent_labels, index=current_index,
                key="agent_dropdown", label_visibility="collapsed",
            )
            st.session_state.selected_agent = agent_ids[agent_labels.index(selected_label)]
            # When agent changes, switch to the latest session for that agent (or create new)
            current_session_agent = st.session_state.session.agent_id if st.session_state.session else None
            if current_session_agent != st.session_state.selected_agent:
                _save_current_session()
                # Do NOT disconnect — keep ACP processes alive for all sessions
                all_sessions = auth_manager.list_sessions(username)
                agent_sessions = [s for s in all_sessions if s.agent_id == st.session_state.selected_agent]
                if agent_sessions:
                    # Resume the most recent session for this agent
                    latest = agent_sessions[0]
                    loaded = auth_manager.load_session(username, latest.session_id)
                    ws = workspace_manager.get_workspace(username, latest.session_id) or \
                         workspace_manager.create_workspace(username, latest.session_id)
                    st.session_state.session = loaded
                    st.session_state.workspace = ws
                    st.session_state.messages = _load_session_messages(loaded)
                else:
                    new_sess = auth_manager.create_session(username)
                    new_sess.agent_id = st.session_state.selected_agent
                    auth_manager.save_session(new_sess)
                    ws = workspace_manager.create_workspace(username, new_sess.session_id)
                    st.session_state.session = new_sess
                    st.session_state.workspace = ws
                    st.session_state.messages = []
                st.session_state.acp_connected = False
                st.rerun()
            selected = get_agent(st.session_state.selected_agent, workspace_path)
            if selected and selected.description:
                st.caption(selected.description)
        else:
            st.caption("No agents found. Add `.json` files to `~/.kiro/agents/`.")

        session_id = st.session_state.session.session_id if st.session_state.session else ""
        status = acp_client.get_status(username, st.session_state.selected_agent or "", session_id)
        status_map = {
            AgentStatus.RUNNING: ("🟢", "Running"), AgentStatus.IDLE: ("🔵", "Connected"),
            AgentStatus.INITIALIZING: ("🟡", "Connecting..."),
            AgentStatus.STOPPED: ("⚪", "Disconnected"), AgentStatus.ERROR: ("🟠", "Error"),
        }
        icon, label = status_map.get(status, ("⚪", "Unknown"))
        st.caption(f"{icon} {label}")

        st.markdown("---")

        # Session list with New Session at top
        st.markdown("#### 📋 SESSIONS")

        if st.button("➕ New Session", use_container_width=True):
            _save_current_session()
            acp_client.disconnect(username)
            session = auth_manager.create_session(st.session_state.username)
            session.agent_id = st.session_state.selected_agent or ""
            auth_manager.save_session(session)
            workspace = workspace_manager.create_workspace(
                st.session_state.username, session.session_id
            )
            st.session_state.session = session
            st.session_state.workspace = workspace
            st.session_state.messages = []
            st.session_state.acp_connected = False
            st.rerun()

        sessions = auth_manager.list_sessions(username)
        current_agent = st.session_state.selected_agent or ""
        sessions = [s for s in sessions if s.agent_id == current_agent]

        if not sessions:
            st.caption("No previous sessions")
        else:
            current_session_id = (
                st.session_state.session.session_id if st.session_state.session else None
            )

            def _render_session_btn(sess):
                title = sess.title or "New Session"
                from datetime import datetime
                time_str = datetime.fromtimestamp(sess.last_active).strftime("%m/%d %H:%M")
                is_current = sess.session_id == current_session_id
                editing_key = f"editing_{sess.session_id}"

                if st.session_state.get(editing_key):
                    # Inline rename input
                    new_title = st.text_input(
                        "rename",
                        value=title,
                        key=f"rename_input_{sess.session_id}",
                        label_visibility="collapsed",
                    )
                    col_ok, col_cancel = st.columns(2)
                    with col_ok:
                        if st.button("✓", key=f"rename_ok_{sess.session_id}", use_container_width=True):
                            sess.title = new_title.strip() or title
                            auth_manager.save_session(sess)
                            if is_current and st.session_state.session:
                                st.session_state.session.title = sess.title
                            st.session_state[editing_key] = False
                            st.rerun()
                    with col_cancel:
                        if st.button("✕", key=f"rename_cancel_{sess.session_id}", use_container_width=True):
                            st.session_state[editing_key] = False
                            st.rerun()
                else:
                    display = title if len(title) <= 28 else title[:28] + "..."
                    col_btn, col_edit, col_del = st.columns([5, 1, 1])
                    with col_btn:
                        if st.button(
                            f"{'▶ ' if is_current else ''}{display}",
                            key=f"sess_{sess.session_id}",
                            use_container_width=True,
                            type="primary" if is_current else "secondary",
                            help=f"{time_str}",
                        ):
                            if not is_current:
                                _switch_to_session(sess)
                    with col_edit:
                        if st.button("✏️", key=f"edit_{sess.session_id}", help="Rename"):
                            st.session_state[editing_key] = True
                            st.rerun()
                    with col_del:
                        if st.button("🗑️", key=f"del_{sess.session_id}", help="Delete"):
                            auth_manager.delete_session(username, sess.session_id)
                            if is_current:
                                acp_client.disconnect(username)
                                new_sess = auth_manager.create_session(username)
                                new_ws = workspace_manager.create_workspace(username, new_sess.session_id)
                                st.session_state.session = new_sess
                                st.session_state.workspace = new_ws
                                st.session_state.messages = []
                                st.session_state.acp_connected = False
                            st.rerun()

            for sess in sessions[:5]:
                _render_session_btn(sess)

            if len(sessions) > 5:
                with st.expander(f"older ({len(sessions) - 5})"):
                    for sess in sessions[5:]:
                        _render_session_btn(sess)

        st.markdown("---")

        # User info + Sign Out at the bottom
        col_user, col_out = st.columns([3, 1])
        with col_user:
            st.caption(f"👤 {st.session_state.user.display_name} (@{username})")
        with col_out:
            if st.button("🚪", key="signout_btn", help="Sign Out"):
                _save_current_session()
                acp_client.disconnect(username)
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                init_session_state()
                st.rerun()


def _save_current_session():
    """Save session metadata (title, last_active). Messages live in kiro jsonl."""
    if not st.session_state.session:
        return
    session = st.session_state.session
    # Sync acp_session_ids from disk (written by bg callback) before saving
    fresh = auth_manager.load_session(session.username, session.session_id)
    if fresh:
        session.acp_session_ids = fresh.acp_session_ids
    session.last_active = time.time()
    if not session.title:
        for msg in st.session_state.messages:
            if msg["role"] == "user":
                session.title = msg["content"][:60]
                break
    auth_manager.save_session(session)


def _load_session_messages(session) -> list[dict]:
    """Load messages from kiro jsonl for the given session."""
    # Always reload from disk to get the latest acp_session_ids written by the bg callback
    fresh = auth_manager.load_session(session.username, session.session_id)
    if fresh:
        session.acp_session_ids = fresh.acp_session_ids  # sync in-memory object
    acp_sid = session.acp_session_ids.get(session.agent_id, "")
    import logging
    logging.getLogger(__name__).info(f"_load_session_messages: agent={session.agent_id} acp_sid={acp_sid} acp_session_ids={session.acp_session_ids}")
    if acp_sid:
        return load_kiro_messages(acp_sid)
    return []


def _switch_to_session(sess):
    """Switch to an existing session."""
    _save_current_session()
    username = st.session_state.username

    # Do NOT disconnect — keep ACP processes alive for all sessions
    # Load the session
    loaded = auth_manager.load_session(username, sess.session_id)
    if loaded:
        workspace = workspace_manager.get_workspace(username, loaded.session_id)
        if not workspace:
            workspace = workspace_manager.create_workspace(username, loaded.session_id)

        st.session_state.session = loaded
        st.session_state.workspace = workspace
        st.session_state.messages = _load_session_messages(loaded)
        st.session_state.selected_agent = loaded.agent_id or None
        st.session_state.acp_connected = False
        st.rerun()


def render_chat():
    """Render the main chat interface."""

    if not config.kiro_api_key:
        st.warning(
            "⚠️ KIRO_API_KEY not configured. Set it in `.env` to enable agent functionality."
        )

    workspace_path = st.session_state.workspace.path if st.session_state.workspace else None
    agents = load_agents(workspace_path)

    for msg in st.session_state.messages:
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.markdown(msg["content"])
        else:
            with st.chat_message("assistant", avatar="🤖"):
                if agent_name := msg.get("agent_name"):
                    st.caption(agent_name)
                st.markdown(msg["content"])

    if prompt := st.chat_input("Describe what you need...", disabled=st.session_state.get("agent_running")):
        agent_id = st.session_state.selected_agent or ""
        agent_name = next((a.name for a in agents if a.id == agent_id), agent_id or "Agent")

        st.session_state.messages.append({"role": "user", "content": prompt})
        st.session_state.agent_running = True
        st.session_state.pending_agent_id = agent_id
        st.session_state.pending_agent_name = agent_name
        st.session_state.pending_prompt = prompt
        st.session_state.agent_result = None
        st.rerun()

    if st.session_state.get("agent_running"):
        agent_id = st.session_state.pending_agent_id
        agent_name = st.session_state.pending_agent_name
        prompt = st.session_state.pending_prompt

        with st.chat_message("assistant", avatar="🤖"):
            st.caption(agent_name)
            if st.session_state.agent_result is None:
                import concurrent.futures
                _username = st.session_state.username
                _workspace_path = st.session_state.workspace.path if st.session_state.workspace else None
                _session_id = st.session_state.session.session_id if st.session_state.session else ""
                with st.spinner("Thinking..."):
                    col_cancel = st.empty()
                    if col_cancel.button("⏹ Cancel", key="cancel_btn"):
                        acp_client.cancel(_username, agent_id, _session_id)
                        st.session_state.agent_running = False
                        st.session_state.messages.append({"role": "assistant", "content": "*(cancelled)*", "agent_name": agent_name})
                        _save_current_session()
                        st.rerun()
                    with concurrent.futures.ThreadPoolExecutor() as ex:
                        future = ex.submit(execute_agent_prompt, prompt, _username, _workspace_path, agent_id, _session_id)
                        try:
                            response = future.result()
                        except Exception:
                            response = None
                # If cancel was already handled (agent_running=False), skip appending result
                if not st.session_state.get("agent_running"):
                    st.rerun()
                if response:
                    st.session_state.agent_running = False
                    st.markdown(response)
                    st.session_state.messages.append({"role": "assistant", "content": response, "agent_name": agent_name})
                    _save_current_session()
                    st.rerun()


def execute_agent_prompt(prompt: str, username: str = None, workspace_path=None, agent_id: str = "", session_id: str = "") -> str:
    """Execute a prompt via Kiro CLI ACP protocol with the selected agent."""
    if username is None:
        username = st.session_state.username
    if workspace_path is None:
        if not st.session_state.workspace:
            return "❌ No workspace available. Please create a new session."
        workspace_path = st.session_state.workspace.path
    if not agent_id:
        agent_id = st.session_state.selected_agent or ""
    if not session_id:
        session_id = st.session_state.session.session_id if st.session_state.session else ""

    try:
        response = acp_client.prompt(username, workspace_path, prompt, agent_id=agent_id, session_id=session_id)
        return response

    except FileNotFoundError as e:
        return (
            f"❌ **Kiro CLI not found**\n\n{e}\n\n"
            f"Install: https://kiro.dev/cli/\n"
            f"Or set `KIRO_CLI_PATH` in `.env`."
        )

    except ConnectionError as e:
        return f"❌ **Connection lost**\n\n{e}\n\nTry sending another message to reconnect."

    except TimeoutError:
        return "⏳ **Timed out** — try a simpler prompt or check network."

    except RuntimeError as e:
        return (
            f"❌ **Agent error**\n\n{e}\n\n"
            f"Check: Kiro CLI v1.25+, `kiro-cli acp` works, logged in via `kiro-cli login`."
        )

    except Exception as e:
        return f"❌ Unexpected error: {type(e).__name__}: {e}"


# --- Main ---
def main():
    """Main application entry point."""
    pg = st.navigation(
        [
            st.Page(lambda: (render_login_page() if not st.session_state.authenticated else (render_sidebar(), render_chat())),
                    title="Chat", icon="🤖", default=True),
            st.Page("pages/skills.py", title="Skills", icon="⚡"),
            st.Page("pages/mcp.py", title="MCP", icon="🔌"),
        ],
        position="sidebar",
    )
    pg.run()


if __name__ == "__main__":
    main()
