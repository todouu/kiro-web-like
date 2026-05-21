"""
Kiro Web-Like: Main Streamlit Application

A browser-based interface for interacting with Kiro CLI agents via ACP
(Agent Client Protocol), featuring per-user isolated workspaces and
persistent multi-turn conversation sessions.
"""

import time

import streamlit as st

from src.agent import ACPClient, AgentStatus, acp_client
from src.auth import AuthManager, Session
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
    /* Dark theme styling similar to Kiro Web */
    .stApp {
        background-color: #1a1a2e;
    }
    .main-header {
        color: #e0e0e0;
        font-size: 1.5rem;
        font-weight: 600;
        padding: 0.5rem 0;
    }
    .chat-message-user {
        background-color: #2d2d44;
        border-radius: 12px;
        padding: 12px 16px;
        margin: 8px 0;
        border-left: 3px solid #6366f1;
    }
    .chat-message-assistant {
        background-color: #1e1e36;
        border-radius: 12px;
        padding: 12px 16px;
        margin: 8px 0;
        border-left: 3px solid #22c55e;
    }
    .status-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 500;
    }
    .status-running { background-color: #22c55e33; color: #22c55e; }
    .status-idle { background-color: #6366f133; color: #6366f1; }
    .status-stopped { background-color: #ef444433; color: #ef4444; }
    .sidebar-section {
        border-bottom: 1px solid #333;
        padding: 12px 0;
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
        "mode": "vibe",
        "repos": [],
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
    """Render the application sidebar."""
    with st.sidebar:
        # User info
        st.markdown(f"### 👤 {st.session_state.user.display_name}")
        st.caption(f"@{st.session_state.username}")

        st.markdown("---")

        # Mode selector
        st.markdown("#### Mode")
        mode = st.radio(
            "Select mode",
            options=["vibe", "autonomous"],
            format_func=lambda x: "🎯 Vibe (Collaborative)" if x == "vibe" else "🚀 Autonomous",
            index=0 if st.session_state.mode == "vibe" else 1,
            label_visibility="collapsed",
        )
        if mode != st.session_state.mode:
            st.session_state.mode = mode

        if mode == "vibe":
            st.caption("Work interactively with the agent.")
        else:
            st.caption("Agent works independently, opens PRs.")

        st.markdown("---")

        # Repository management
        st.markdown("#### Repositories")
        repo_url = st.text_input(
            "Add Repository",
            placeholder="https://github.com/owner/repo",
            label_visibility="collapsed",
        )
        col1, col2 = st.columns(2)
        with col1:
            branch = st.text_input("Branch", value="main", label_visibility="collapsed")
        with col2:
            if st.button("Clone", use_container_width=True):
                if repo_url and st.session_state.workspace:
                    with st.spinner("Cloning repository..."):
                        try:
                            repo_path = workspace_manager.clone_repo(
                                st.session_state.workspace, repo_url, branch
                            )
                            repo_name = repo_path.name
                            if repo_name not in st.session_state.repos:
                                st.session_state.repos.append(repo_name)
                            st.success(f"Cloned: {repo_name}")
                        except Exception as e:
                            st.error(f"Clone failed: {e}")

        # Show cloned repos
        if st.session_state.repos:
            for repo in st.session_state.repos:
                st.markdown(f"📁 `{repo}`")

        st.markdown("---")

        # Session & Agent info
        st.markdown("#### Session")
        if st.session_state.session:
            st.caption(f"ID: `{st.session_state.session.session_id[:8]}...`")

        # Agent status from ACP
        username = st.session_state.username
        status = acp_client.get_status(username)
        status_display = {
            AgentStatus.RUNNING: ("🟢", "Running"),
            AgentStatus.IDLE: ("🔵", "Connected"),
            AgentStatus.INITIALIZING: ("🟡", "Connecting..."),
            AgentStatus.STOPPED: ("🔴", "Disconnected"),
            AgentStatus.ERROR: ("🟠", "Error"),
        }
        icon, label = status_display.get(status, ("⚪", "Unknown"))
        st.markdown(f"Agent: {icon} {label}")

        st.markdown("---")

        # Actions
        if st.button("🗑️ Clear Chat", use_container_width=True):
            # Close ACP session and start fresh
            conn = acp_client.get_connection(username)
            if conn:
                acp_client.close_session(conn)
            st.session_state.messages = []
            st.session_state.acp_connected = False
            st.rerun()

        if st.button("🔄 New Session", use_container_width=True):
            # Disconnect ACP and create a new workspace session
            acp_client.disconnect(username)

            session = auth_manager.create_session(st.session_state.username)
            workspace = workspace_manager.create_workspace(
                st.session_state.username, session.session_id
            )
            st.session_state.session = session
            st.session_state.workspace = workspace
            st.session_state.messages = []
            st.session_state.repos = []
            st.session_state.acp_connected = False
            st.rerun()

        if st.button("🚪 Sign Out", use_container_width=True):
            # Full cleanup
            acp_client.disconnect(username)

            for key in list(st.session_state.keys()):
                del st.session_state[key]
            init_session_state()
            st.rerun()


def render_chat():
    """Render the main chat interface."""
    # Header
    mode_label = "Vibe" if st.session_state.mode == "vibe" else "Autonomous"
    st.markdown(f"### 🤖 Kiro Agent — {mode_label} Mode")

    if not config.kiro_api_key:
        st.warning(
            "⚠️ KIRO_API_KEY not configured. Set it in `.env` to enable agent functionality."
        )

    # Chat messages container
    chat_container = st.container()

    with chat_container:
        for msg in st.session_state.messages:
            if msg["role"] == "user":
                with st.chat_message("user"):
                    st.markdown(msg["content"])
            else:
                with st.chat_message("assistant", avatar="🤖"):
                    st.markdown(msg["content"])

    # Chat input
    if prompt := st.chat_input("Describe what you want to build or ask a question..."):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("user"):
            st.markdown(prompt)

        # Send to agent via ACP
        with st.chat_message("assistant", avatar="🤖"):
            with st.spinner("Kiro is thinking..."):
                response = execute_agent_prompt(prompt)
            st.markdown(response)

        st.session_state.messages.append({"role": "assistant", "content": response})
        st.rerun()


def ensure_acp_connection():
    """Ensure the ACP connection is established for the current user."""
    username = st.session_state.username
    workspace_path = st.session_state.workspace.path

    # Check if already connected
    conn = acp_client.get_connection(username)
    if conn and conn.status in (AgentStatus.IDLE, AgentStatus.RUNNING):
        return conn

    # Connect (spawns kiro-cli acp + initialize handshake)
    conn = acp_client.connect(username, workspace_path)

    # Create a new ACP session for conversation
    acp_client.new_session(conn)
    st.session_state.acp_connected = True

    return conn


def execute_agent_prompt(prompt: str) -> str:
    """
    Execute a prompt via Kiro CLI ACP protocol.

    Unlike headless mode, ACP maintains conversation context automatically.
    Each message is sent within the same session, so the agent remembers
    previous messages without us having to re-send history.
    """
    if not config.kiro_api_key:
        return (
            "⚠️ **Agent not configured.**\n\n"
            "Please set `KIRO_API_KEY` in your `.env` file to enable Kiro CLI agent.\n\n"
            "```bash\n"
            "export KIRO_API_KEY=your_api_key_here\n"
            "```"
        )

    if not st.session_state.workspace:
        return "❌ No workspace available. Please create a new session."

    try:
        # Ensure ACP connection is live
        conn = ensure_acp_connection()

        # Send prompt — ACP keeps multi-turn context server-side
        response = acp_client.prompt(conn, prompt)
        return response

    except FileNotFoundError as e:
        return (
            f"❌ **Kiro CLI not found**\n\n"
            f"{e}\n\n"
            f"Install it from: https://kiro.dev/cli/\n\n"
            f"Or set `KIRO_CLI_PATH` in `.env` if it's in a custom location."
        )

    except ConnectionError as e:
        st.session_state.acp_connected = False
        return (
            f"❌ **Connection lost to Kiro agent**\n\n"
            f"{e}\n\n"
            f"The agent process may have crashed. Try sending another message to reconnect."
        )

    except TimeoutError:
        return (
            "⏳ **Agent timed out**\n\n"
            "The agent took too long to respond (>3 min). "
            "Try a simpler prompt or check your network connection."
        )

    except RuntimeError as e:
        return (
            f"❌ **Agent error**\n\n"
            f"{e}\n\n"
            f"**Troubleshooting:**\n"
            f"- Check that `KIRO_API_KEY` is valid and not expired\n"
            f"- Ensure Kiro CLI is v1.25+ (ACP support required)\n"
            f"- Test manually: `kiro-cli acp` (should start and wait for JSON-RPC input)\n"
        )

    except Exception as e:
        return f"❌ Unexpected error: {type(e).__name__}: {e}"


def render_workspace_panel():
    """Render workspace file browser panel (optional right panel)."""
    if st.session_state.workspace and st.session_state.workspace.exists:
        workspace_path = st.session_state.workspace.path
        files = list(workspace_path.rglob("*"))
        if files:
            st.markdown("#### 📂 Workspace Files")
            for f in sorted(files)[:50]:  # Limit display
                if f.is_file():
                    rel_path = f.relative_to(workspace_path)
                    st.caption(f"📄 {rel_path}")


# --- Main App Layout ---
def main():
    """Main application entry point."""
    if not st.session_state.authenticated:
        render_login_page()
    else:
        render_sidebar()

        # Main content area
        col_chat, col_files = st.columns([3, 1])

        with col_chat:
            render_chat()

        with col_files:
            render_workspace_panel()


if __name__ == "__main__":
    main()
