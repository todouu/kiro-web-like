# Kiro Web-Like

A browser-based development interface inspired by [Kiro Web](https://kiro.dev/web/), built with **Streamlit** frontend and powered by **Kiro CLI headless agents**.

Each user gets an isolated workspace and independent agent session — just like the real Kiro Web experience.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Browser (User)                       │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              Streamlit Frontend (app.py)              │
│  ┌──────────┐  ┌───────────┐  ┌──────────────────┐ │
│  │  Auth UI │  │  Chat UI  │  │ Workspace Panel  │ │
│  └──────────┘  └───────────┘  └──────────────────┘ │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│               Backend Services (src/)                 │
│  ┌──────────┐  ┌───────────┐  ┌──────────────────┐ │
│  │   Auth   │  │  Agent    │  │    Workspace     │ │
│  │ Manager  │  │  Manager  │  │    Manager       │ │
│  └──────────┘  └─────┬─────┘  └──────────────────┘ │
└───────────────────────┼─────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────┐
│            Kiro CLI (Headless Mode)                   │
│                                                       │
│  kiro --no-interactive --trust-all-tools --prompt ... │
│                                                       │
│  Per-user subprocess with isolated workspace (cwd)   │
└──────────────────────────────────────────────────────┘
```

## Features

- **User Authentication** — Register/login with bcrypt password hashing
- **Isolated Workspaces** — Each session gets its own filesystem workspace
- **Dual Modes** — Vibe (collaborative) and Autonomous mode support
- **Git Integration** — Clone repos directly into your workspace
- **Agent Chat** — Real-time conversation with Kiro CLI agents
- **Session Management** — Multiple sessions, cleanup, new session creation
- **Dark Theme** — Matches the Kiro Web aesthetic
- **Docker Support** — One-command deployment with Docker Compose

## Prerequisites

- Python 3.11+
- [Kiro CLI](https://kiro.dev/cli/) installed and in PATH
- A valid `KIRO_API_KEY` (generate from Kiro settings)

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/todouu/kiro-web-like.git
cd kiro-web-like
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and set your KIRO_API_KEY
```

### 4. Run the application

```bash
streamlit run app.py
```

Open your browser at `http://localhost:8501`

## Docker Deployment

```bash
# Set environment variables
export KIRO_API_KEY=your_key_here
export APP_SECRET_KEY=$(openssl rand -hex 32)

# Start the service
docker-compose up -d
```

## Project Structure

```
kiro-web-like/
├── app.py                  # Main Streamlit application
├── src/
│   ├── __init__.py
│   ├── config.py           # Configuration management
│   ├── auth.py             # User authentication & sessions
│   ├── workspace.py        # Workspace isolation & git ops
│   └── agent.py            # Kiro CLI process management
├── .streamlit/
│   └── config.toml         # Streamlit theme & server config
├── Dockerfile              # Container image
├── docker-compose.yml      # Docker Compose config
├── requirements.txt        # Python dependencies
├── pyproject.toml          # Project metadata
├── .env.example            # Environment template
└── README.md               # This file
```

## How It Works

1. **User signs in** → Auth module validates credentials (bcrypt)
2. **Session created** → Unique session ID generated, workspace directory allocated
3. **Clone repos** → Git repos cloned into user's isolated workspace
4. **Chat with agent** → Messages sent to Kiro CLI via `--no-interactive` headless mode
5. **Agent executes** → Kiro CLI runs in workspace directory, has full tool access
6. **Results streamed** → Agent output captured and displayed in chat UI

## Kiro CLI Headless Mode

The backend spawns Kiro CLI processes with:

```bash
kiro --no-interactive --trust-all-tools --prompt "user message"
```

Environment:
- `KIRO_API_KEY` — Authentication token
- Working directory set to user's workspace
- Output captured via stdout pipe

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `KIRO_API_KEY` | Kiro CLI API key | (required) |
| `APP_SECRET_KEY` | Session signing secret | `change-me-in-production` |
| `WORKSPACES_ROOT` | User workspace base path | `/tmp/kiro-workspaces` |
| `DATA_DIR` | Application data directory | `./data` |
| `KIRO_CLI_PATH` | Path to kiro binary | `kiro` |

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run linting
ruff check src/ app.py

# Run the app in dev mode
streamlit run app.py --server.runOnSave=true
```

## Security Considerations

- Passwords hashed with bcrypt
- Sessions use cryptographic tokens
- Workspaces are filesystem-isolated per user
- XSRF protection enabled in Streamlit
- Consider adding rate limiting for production
- Use HTTPS reverse proxy (nginx/caddy) in production

## License

MIT
