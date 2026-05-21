"""Skills Page — Shows real skills from ~/.kiro/skills/ and .kiro/skills/."""

import streamlit as st
from pathlib import Path

from src.skills_config import load_skills, get_skill_content

st.set_page_config(page_title="Skills — Kiro Web", page_icon="⚡", layout="wide")

st.markdown(
    """
<style>
    .stApp { background-color: #1a1a2e; }
    .skill-card {
        background-color: #2d2d44;
        border-radius: 12px;
        padding: 16px;
        margin: 8px 0;
        border: 1px solid #3d3d5c;
    }
</style>
""",
    unsafe_allow_html=True,
)

st.markdown("# ⚡ Skills")
st.markdown(
    "Skills are portable instruction packages from your Kiro configuration. "
    "They extend what the agent knows how to do."
)
st.markdown(
    "> Scanned from `~/.kiro/skills/` (global) and `.kiro/skills/` (workspace)"
)
st.markdown("---")

# Load real skills
workspace_path = None
if "workspace" in st.session_state and st.session_state.workspace:
    workspace_path = st.session_state.workspace.path

skills = load_skills(workspace_path)

if not skills:
    st.info(
        "No skills found.\n\n"
        "Add `.md` files to `~/.kiro/skills/` to register skills.\n\n"
        "Example:\n"
        "```markdown\n"
        "---\n"
        "name: Code Review\n"
        "description: Reviews code for bugs and best practices\n"
        "---\n"
        "Your skill instructions here...\n"
        "```"
    )
else:
    # Group by scope
    global_skills = [s for s in skills if s.scope == "global"]
    workspace_skills = [s for s in skills if s.scope == "workspace"]

    if global_skills:
        st.markdown("### 🌐 Global Skills")
        st.caption(f"From `~/.kiro/skills/` — {len(global_skills)} skill(s)")
        st.markdown("")

        for skill in global_skills:
            with st.expander(f"**{skill.name}**" + (f" — {skill.description}" if skill.description else ""), expanded=False):
                st.caption(f"📄 `{skill.file_path}`")
                if skill.content:
                    st.markdown(skill.content[:2000])
                    if len(skill.content) > 2000:
                        st.caption("(content truncated)")
                else:
                    st.caption("(empty body)")

    if workspace_skills:
        st.markdown("### 📁 Workspace Skills")
        st.caption(f"From `.kiro/skills/` — {len(workspace_skills)} skill(s)")
        st.markdown("")

        for skill in workspace_skills:
            with st.expander(f"**{skill.name}**" + (f" — {skill.description}" if skill.description else ""), expanded=False):
                st.caption(f"📄 `{skill.file_path}`")
                if skill.content:
                    st.markdown(skill.content[:2000])
                    if len(skill.content) > 2000:
                        st.caption("(content truncated)")
                else:
                    st.caption("(empty body)")

    # Summary
    st.markdown("---")
    st.caption(f"Total: {len(skills)} skill(s) — {len(global_skills)} global, {len(workspace_skills)} workspace")
