"""MCP Page — Shows real MCP servers from ~/.kiro/settings/mcp.json."""

import streamlit as st
from pathlib import Path

from src.mcp_config import load_mcp_servers

st.set_page_config(page_title="MCP — Kiro Web", page_icon="🔌", layout="wide")

st.markdown(
    """
<style>
    .stApp { background-color: #1a1a2e; }
</style>
""",
    unsafe_allow_html=True,
)


def render_server(server):
    """Render a single MCP server card."""
    status_icon = "🟢" if not server.disabled else "⚫"
    transport_badge = "stdio" if server.transport == "stdio" else "HTTP"
    disabled_label = " *(disabled)*" if server.disabled else ""

    with st.expander(
        f"{status_icon} **{server.name}** — `{transport_badge}`{disabled_label}",
        expanded=False,
    ):
        st.markdown(f"**Transport:** `{server.transport}`")
        st.markdown(f"**Command:** `{server.command}`")

        if server.env:
            st.markdown("**Environment variables:**")
            for key, val in server.env.items():
                # Mask sensitive values
                display_val = val if not any(
                    s in key.upper() for s in ["TOKEN", "KEY", "SECRET", "PASSWORD"]
                ) else "••••••"
                st.code(f"{key}={display_val}", language=None)

        if server.auto_approve:
            st.markdown(f"**Auto-approved tools:** `{'`, `'.join(server.auto_approve)}`")

        if server.disabled_tools:
            st.markdown(f"**Disabled tools:** `{'`, `'.join(server.disabled_tools)}`")

        if server.disabled:
            st.warning("This server is disabled.")


# --- Page content ---
st.markdown("# 🔌 MCP SERVERS")
st.markdown(
    "Model Context Protocol (MCP) servers provide tools that agents use to interact with "
    "external systems — filesystems, APIs, databases, and more."
)
st.markdown(
    "> Scanned from `~/.kiro/settings/mcp.json` (global) and `.kiro/settings/mcp.json` (workspace)"
)
st.markdown("---")

# Load real MCP config
workspace_path = None
if "workspace" in st.session_state and st.session_state.workspace:
    workspace_path = st.session_state.workspace.path

servers = load_mcp_servers(workspace_path)

if not servers:
    st.info(
        "No MCP servers configured.\n\n"
        "Add servers to `~/.kiro/settings/mcp.json`:\n\n"
        "```json\n"
        '{\n'
        '  "mcpServers": {\n'
        '    "my-server": {\n'
        '      "command": "npx",\n'
        '      "args": ["-y", "@my/mcp-server"],\n'
        '      "env": {}\n'
        '    }\n'
        '  }\n'
        '}\n'
        "```"
    )
else:
    # Group by scope
    global_servers = [s for s in servers if s.scope == "global"]
    workspace_servers = [s for s in servers if s.scope == "workspace"]

    if global_servers:
        st.markdown("### 🌐 GLOBAL MCP SERVERS")
        st.caption(f"From `~/.kiro/settings/mcp.json` — {len(global_servers)} server(s)")
        st.markdown("")

        for server in global_servers:
            render_server(server)

    if workspace_servers:
        st.markdown("### 📁 WORKSPACE MCP SERVERS")
        st.caption(f"From `.kiro/settings/mcp.json` — {len(workspace_servers)} server(s)")
        st.markdown("")

        for server in workspace_servers:
            render_server(server)

    # Summary
    st.markdown("---")
    st.caption(f"Total: {len(servers)} server(s) — {len(global_servers)} global, {len(workspace_servers)} workspace")
