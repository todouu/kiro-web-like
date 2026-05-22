# Kiro Web-Like

[English README](README.md)

基于 Streamlit 构建的多用户 [Kiro CLI](https://kiro.dev/cli/) 浏览器聊天界面。每个用户拥有隔离的工作区，每个 Agent 和对话窗口对应独立的 ACP 进程与上下文。

---

## 架构

```
浏览器（用户）
     │
     ▼
Streamlit (app.py)
  ├── 认证界面（登录 / 注册）
  ├── 聊天界面  ─────────────────────────────────────┐
  ├── 会话列表（按 Agent 过滤）                      │
  └── Agent 选择器                                   │
                                                     │
src/agent.py — ACPClient                             │
  ├── 一个后台 asyncio 事件循环（daemon 线程）        │
  ├── 每个 (username × agent_id × session_id) 一个进程│◄──┘
  │     kiro-cli acp --agent <id>                    │
  │     空闲 30 分钟自动退出                          │
  │     重启后通过 session/load 恢复上下文            │
  └── 每进程一个 asyncio.Queue 分发 prompt

data/sessions/<user>/          ← 会话元数据（title、agent_id、acp_session_ids）
~/.kiro/sessions/cli/          ← 聊天历史与 AI 上下文（由 kiro-cli 管理）
```

## 功能

- **用户认证** — 注册/登录，bcrypt 密码哈希
- **多 Agent** — 从 `~/.kiro/agents/*.json` 加载 Agent 配置；每个 Agent 以独立的 `kiro-cli acp --agent <name>` 进程运行
- **会话隔离** — 每个对话窗口拥有独立的 kiro-cli 进程和 context window
- **持久上下文** — ACP 会话在应用重启后通过 `session/load` 恢复；空闲进程自动退出，下次发消息时自动重连
- **聊天历史来自 kiro** — 消息从 `~/.kiro/sessions/cli/*.jsonl` 读取，不存储在应用数据库中
- **取消请求** — 支持中途取消正在进行的 Agent 响应
- **会话管理** — 创建、重命名、删除会话；按 Agent 过滤会话列表
- **Anthropic Light 主题** — 简洁暖白色 UI
- **多页面** — 🤖 Chat / ⚡ Skills / 🔌 MCP

## 前置要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip
- [Kiro CLI](https://kiro.dev/cli/) 已安装（`~/.local/bin/kiro-cli`）
- 已通过 `kiro-cli login` 登录

## 快速开始

```bash
git clone https://github.com/todouu/kiro-web-like.git
cd kiro-web-like

cp .env.example .env
# 编辑 .env，设置 KIRO_API_KEY 和 APP_SECRET_KEY

uv sync
uv run streamlit run app.py
```

浏览器打开 `http://localhost:8501`

## 配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `KIRO_API_KEY` | Kiro API Key | （必填） |
| `KIRO_CLI_PATH` | kiro-cli 二进制路径 | `kiro-cli` |
| `APP_SECRET_KEY` | Session 签名密钥 | `change-me-in-production` |
| `WORKSPACES_ROOT` | 用户工作区根目录 | `/tmp/kiro-workspaces` |
| `DATA_DIR` | 会话元数据目录 | `./data` |

如果 `kiro-cli` 不在 PATH 中（常见于 systemd 或非登录 shell），请设置 `KIRO_CLI_PATH=/home/<user>/.local/bin/kiro-cli`。

## 项目结构

```
kiro-web-like/
├── app.py                  # Streamlit 主应用（Chat 页面）
├── pages/
│   ├── skills.py           # ⚡ Skills 页面
│   └── mcp.py              # 🔌 MCP 页面
├── src/
│   ├── agent.py            # ACP 进程管理（持久会话）
│   ├── auth.py             # 用户认证与会话元数据
│   ├── kiro_session.py     # 从 kiro jsonl 读取聊天历史
│   ├── agents_config.py    # 从 ~/.kiro/agents/ 加载 Agent 配置
│   ├── mcp_config.py       # MCP Server 配置
│   ├── skills_config.py    # Skills 配置
│   ├── workspace.py        # 用户工作区管理
│   └── config.py           # 应用配置
├── .streamlit/
│   └── config.toml         # 主题（Anthropic Light）与服务配置
├── data/                   # 会话元数据（已加入 .gitignore）
├── pyproject.toml
├── .env.example
└── README.md
```

## ACP 会话生命周期

```
首次在某个会话发消息
  → 启动 kiro-cli acp --agent <id>（cwd = 用户工作区）
  → initialize + session/new
  → 将 kiro session_id 保存到 data/sessions/

同一会话后续消息
  → 复用已有进程，通过 asyncio.Queue 分发

应用重启 / 空闲超时（30 分钟）
  → 进程退出
  → 下次发消息：启动新进程 + session/load <已保存的 session_id>
  → kiro-cli 从 ~/.kiro/sessions/cli/ 恢复完整上下文

切换会话 / 切换 Agent
  → 已有进程保持运行（空闲超时负责清理）
  → 新会话在首次发消息时启动独立进程
```

## Docker 部署

```bash
export KIRO_API_KEY=your_key
export APP_SECRET_KEY=$(openssl rand -hex 32)
docker-compose up -d
```

## 安全说明

- 密码使用 bcrypt 哈希存储
- 开启 XSRF 保护
- 工作区按用户做文件系统隔离
- 生产环境建议放在 HTTPS 反向代理（nginx/caddy）之后

## 许可证

MIT
