# Kiro Web-Like

[中文说明](README.zh-CN.md)

A browser-based multi-user chat interface for [Kiro CLI](https://kiro.dev/cli/), built with Streamlit. Each user gets isolated workspaces and persistent ACP sessions per agent and conversation.

---

## Architecture

```
Browser (User)
     │
     ▼
Streamlit (app.py)
  ├── Auth UI (login / register)
  ├── Chat UI  ──────────────────────────────────────────┐
  ├── Session List (per-agent, per-session)              │
  └── Agent Selector                                     │
                                                         │
src/agent.py — ACPClient                                 │
  ├── One background asyncio event loop (daemon thread)  │
  ├── Per (username × agent_id × session_id) ACP process │◄──┘
  │     kiro-cli acp --agent <id>                        │
  │     Persistent: idle 30min → auto-shutdown           │
  │     Resume: session/load on restart                  │
  └── Prompt queue (asyncio.Queue per process)

data/sessions/<user>/          ← session metadata (title, agent_id, acp_session_ids)
~/.kiro/sessions/cli/          ← chat history & AI context (managed by kiro-cli)
```

## Features

- **User auth** — Register/login with bcrypt
- **Multi-agent** — Select from agents defined in `~/.kiro/agents/*.json`; each agent runs as a separate `kiro-cli acp --agent <name>` process
- **Session isolation** — Each conversation window has its own kiro-cli process and context window
- **Persistent context** — ACP sessions survive app restarts via `session/load`; idle processes auto-shutdown after 30 min and resume on next message
- **Chat history from kiro** — Messages loaded from `~/.kiro/sessions/cli/*.jsonl`, not stored in app DB
- **Cancel** — Stop an in-progress agent response mid-stream
- **Session management** — Create, rename, delete sessions; list filtered by agent
- **Anthropic light theme** — Clean warm-white UI via Streamlit theming
- **Multi-page** — 🤖 Chat / ⚡ Skills / 🔌 MCP pages

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- [Kiro CLI](https://kiro.dev/cli/) installed (`~/.local/bin/kiro-cli`)
- Logged in via `kiro-cli login`

## Quick Start

```bash
git clone https://github.com/todouu/kiro-web-like.git
cd kiro-web-like

cp .env.example .env
# Edit .env — set KIRO_API_KEY and APP_SECRET_KEY

uv sync
uv run streamlit run app.py
```

Open `http://localhost:8501`

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `KIRO_API_KEY` | Kiro API key | (required) |
| `KIRO_CLI_PATH` | Path to kiro-cli binary | `kiro-cli` |
| `APP_SECRET_KEY` | Session signing secret | `change-me-in-production` |
| `WORKSPACES_ROOT` | User workspace base path | `/tmp/kiro-workspaces` |
| `DATA_DIR` | Session metadata directory | `./data` |

If `kiro-cli` is not in PATH (common when running via systemd or non-login shells), set `KIRO_CLI_PATH=/home/<user>/.local/bin/kiro-cli`.

## Project Structure

```
kiro-web-like/
├── app.py                  # Main Streamlit app (Chat page)
├── pages/
│   ├── skills.py           # ⚡ Skills page
│   └── mcp.py              # 🔌 MCP page
├── src/
│   ├── agent.py            # ACP process manager (persistent sessions)
│   ├── auth.py             # User auth & session metadata
│   ├── kiro_session.py     # Read chat history from kiro jsonl
│   ├── agents_config.py    # Load agent definitions from ~/.kiro/agents/
│   ├── mcp_config.py       # MCP server config
│   ├── skills_config.py    # Skills config
│   ├── workspace.py        # Per-user workspace management
│   └── config.py           # App configuration
├── .streamlit/
│   └── config.toml         # Theme (anthropic light) & server config
├── data/                   # Session metadata (gitignored)
├── pyproject.toml
├── .env.example
└── README.md
```

## ACP Session Lifecycle

```
First message in a session
  → spawn kiro-cli acp --agent <id>  (cwd = user workspace)
  → initialize + session/new
  → save kiro session_id to data/sessions/

Subsequent messages (same session)
  → reuse existing process + session via asyncio.Queue

App restart / idle timeout (30 min)
  → process exits
  → next message: spawn new process + session/load <saved_session_id>
  → kiro-cli restores full context from ~/.kiro/sessions/cli/

Switch session / switch agent
  → existing processes stay alive (idle timeout handles cleanup)
  → new session gets its own process on first message
```

## Docker

```bash
export KIRO_API_KEY=your_key
export APP_SECRET_KEY=$(openssl rand -hex 32)
docker-compose up -d
```

## Security

- Passwords hashed with bcrypt
- XSRF protection enabled
- Per-user filesystem workspace isolation
- Use HTTPS reverse proxy (nginx/caddy) in production

## License

MIT
