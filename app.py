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
from src.workspace import WorkspaceManager

# --- Page Configuration ---
st.set_page_config(
    page_title="Kiro Web",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Custom CSS ---
st.markdown(
    """
<style>
    .stApp { background-color: #1a1a2e; }
    /* Make the agent dropdown compact and inline-feeling */
    [data-testid="stSelectbox"][aria-label="🤖"] {
        max-width: 200px;
    }
</style>
""",
    unsafe_allow_html=True,
)

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

        # Agent info
        st.markdown("#### 🤖 AGENT")
        workspace_path = None
        if st.session_state.workspace:
            workspace_path = st.session_state.workspace.path
        agents = load_agents(workspace_path)

        if agents:
            agent_ids = [a.id for a in agents]
            agent_labels = [a.name for a in agents]

            current_index = 0
            if st.session_state.selected_agent and st.session_state.selected_agent in agent_ids:
                current_index = agent_ids.index(st.session_state.selected_agent)

            selected_label = st.selectbox(
                "Agent",
                options=agent_labels,
                index=current_index,
                key="agent_dropdown",
                label_visibility="collapsed",
            )

            selected_idx = agent_labels.index(selected_label)
            new_agent_id = agent_ids[selected_idx]

            if new_agent_id != st.session_state.selected_agent:
                st.session_state.selected_agent = new_agent_id
                conn = acp_client.get_connection(username)
                if conn:
                    acp_client.close_session(conn)
                st.session_state.messages = []
                st.session_state.acp_connected = False
                st.rerun()

            # Agent description
            if st.session_state.selected_agent:
                selected = get_agent(st.session_state.selected_agent, workspace_path)
                if selected and selected.description:
                    st.caption(selected.description)

            # Status
            status = acp_client.get_status(username)
            status_map = {
                AgentStatus.RUNNING: ("🟢", "Running"),
                AgentStatus.IDLE: ("🔵", "Connected"),
                AgentStatus.INITIALIZING: ("🟡", "Connecting..."),
                AgentStatus.STOPPED: ("⚪", "Disconnected"),
                AgentStatus.ERROR: ("🟠", "Error"),
            }
            icon, label = status_map.get(status, ("⚪", "Unknown"))
            st.caption(f"{icon} {label}")
        else:
            st.caption("No agents found. Add `.json` files to `~/.kiro/agents/`.")

        st.markdown("---")

        # Session list with New Session at top
        st.markdown("#### 📋 SESSIONS")

        if st.button("➕ New Session", use_container_width=True):
            _save_current_session()
            acp_client.disconnect(username)
            session = auth_manager.create_session(st.session_state.username)
            workspace = workspace_manager.create_workspace(
                st.session_state.username, session.session_id
            )
            st.session_state.session = session
            st.session_state.workspace = workspace
            st.session_state.messages = []
            st.session_state.acp_connected = False
            st.session_state.selected_agent = None
            st.rerun()

        sessions = auth_manager.list_sessions(username)

        if not sessions:
            st.caption("No previous sessions")
        else:
            current_session_id = (
                st.session_state.session.session_id if st.session_state.session else None
            )

            for sess in sessions[:20]:
                title = sess.title or "New Session"
                if len(title) > 35:
                    title = title[:35] + "..."

                from datetime import datetime
                dt = datetime.fromtimestamp(sess.last_active)
                time_str = dt.strftime("%m/%d %H:%M")

                is_current = sess.session_id == current_session_id
                label = f"{'▶ ' if is_current else ''}{title}"

                if st.button(
                    label,
                    key=f"sess_{sess.session_id}",
                    use_container_width=True,
                    type="primary" if is_current else "secondary",
                    help=f"{time_str} · {len(sess.messages)} messages",
                ):
                    if not is_current:
                        _switch_to_session(sess)

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
    """Save current session messages to disk."""
    if st.session_state.session and st.session_state.messages:
        session = st.session_state.session
        session.messages = st.session_state.messages
        session.last_active = time.time()
        session.agent_id = st.session_state.selected_agent or ""
        # Set title from first user message
        if not session.title:
            for msg in st.session_state.messages:
                if msg["role"] == "user":
                    session.title = msg["content"][:60]
                    break
        auth_manager.save_session(session)


def _switch_to_session(sess):
    """Switch to an existing session."""
    _save_current_session()
    username = st.session_state.username

    # Disconnect current ACP
    acp_client.disconnect(username)

    # Load the session
    loaded = auth_manager.load_session(username, sess.session_id)
    if loaded:
        workspace = workspace_manager.get_workspace(username, loaded.session_id)
        if not workspace:
            workspace = workspace_manager.create_workspace(username, loaded.session_id)

        st.session_state.session = loaded
        st.session_state.workspace = workspace
        st.session_state.messages = loaded.messages
        st.session_state.selected_agent = loaded.agent_id or None
        st.session_state.acp_connected = False
        st.rerun()


def render_chat():
    """Render the main chat interface with inline agent selector."""

    if not config.kiro_api_key:
        st.warning(
            "⚠️ KIRO_API_KEY not configured. Set it in `.env` to enable agent functionality."
        )

    # Chat messages
    chat_container = st.container()
    with chat_container:
        for msg in st.session_state.messages:
            if msg["role"] == "user":
                with st.chat_message("user"):
                    st.markdown(msg["content"])
            else:
                with st.chat_message("assistant", avatar="🤖"):
                    st.markdown(msg["content"])

    # Chat input (Streamlit pins this to the bottom)
    if prompt := st.chat_input("Describe what you need..."):
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant", avatar="🤖"):
            with st.spinner("Thinking..."):
                response = execute_agent_prompt(prompt)
            st.markdown(response)

        st.session_state.messages.append({"role": "assistant", "content": response})
        _save_current_session()
        st.rerun()


def ensure_acp_connection():
    """Ensure the ACP connection is established for the current user."""
    username = st.session_state.username
    workspace_path = st.session_state.workspace.path

    conn = acp_client.get_connection(username)
    if conn and conn.status in (AgentStatus.IDLE, AgentStatus.RUNNING):
        return conn

    # connect() now also creates an initial session
    conn = acp_client.connect(username, workspace_path)
    st.session_state.acp_connected = True
    return conn


def execute_agent_prompt(prompt: str) -> str:
    """Execute a prompt via Kiro CLI ACP protocol with the selected agent."""
    if not config.kiro_api_key:
        return (
            "⚠️ **Agent not configured.**\n\n"
            "Please set `KIRO_API_KEY` in your `.env` file.\n\n"
            "```bash\nexport KIRO_API_KEY=your_api_key_here\n```"
        )

    if not st.session_state.workspace:
        return "❌ No workspace available. Please create a new session."

    try:
        conn = ensure_acp_connection()
        response = acp_client.prompt(conn, prompt)
        return response

    except FileNotFoundError as e:
        return (
            f"❌ **Kiro CLI not found**\n\n{e}\n\n"
            f"Install: https://kiro.dev/cli/\n"
            f"Or set `KIRO_CLI_PATH` in `.env`."
        )

    except ConnectionError as e:
        st.session_state.acp_connected = False
        return f"❌ **Connection lost**\n\n{e}\n\nTry sending another message to reconnect."

    except TimeoutError:
        return "⏳ **Timed out** — try a simpler prompt or check network."

    except RuntimeError as e:
        return (
            f"❌ **Agent error**\n\n{e}\n\n"
            f"Check: valid KIRO_API_KEY, Kiro CLI v1.25+, `kiro-cli acp` works."
        )

    except Exception as e:
        return f"❌ Unexpected error: {type(e).__name__}: {e}"


# --- Main ---
def main():
    """Main application entry point."""
    if not st.session_state.authenticated:
        render_login_page()
    else:
        render_sidebar()
        render_chat()


if __name__ == "__main__":
    main()
