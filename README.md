# 🐇 hare

A local TUI terminal assistant powered by Amazon Bedrock AgentCore Harness.

Type in your terminal, AI reasons in the cloud; local tools (Shell / Filesystem) execute on your machine, while enterprise remote tools (MCP / API) are invoked directly in the cloud via AgentCore Gateway.

---

## Architecture

```
Employee's Local Machine
┌──────────────────────────────────────┐
│  hare TUI (Rich + prompt_toolkit)    │
│  ├── User input / streaming output   │
│  └── Local tool execution            │
│      (inline_function)               │
│      shell_run / read_file / write_file │
└─────────────────┬────────────────────┘
                  │ InvokeHarness (boto3 streaming)
                  ▼
Cloud AWS (managed by admin)
┌──────────────────────────────────────────────────────┐
│  AgentCore Harness                                    │
│  ├── Model inference (Claude / GPT / Gemini)         │
│  ├── Agent Loop (tool routing, multi-turn reasoning) │
│  ├── Long-term Memory (AgentCore Memory, admin-bound)│
│  └── Tool routing                                    │
│      ├── inline_function → return for local exec     │
│      └── agentcore_gateway → enterprise MCP server   │
│          (Jira / ERP / Slack, registered by admin)   │
└──────────────────────────────────────────────────────┘
```

### Long-term Memory (AgentCore Memory)

The Harness automatically does two things in every conversation turn:

1. **Recall**: Before inference begins, it retrieves relevant historical memories from Memory and injects them into the context
2. **Write**: After the conversation ends, it distills important information and stores it in Memory for future sessions

Memory is bound at the Harness layer by the admin — employees don't need any extra configuration. After restarting hare, it still remembers what you said last time.

---

## Configuration Overview

| Config Item | Owner | Description |
|-------------|-------|-------------|
| IAM Role + Harness | **Admin** | One-time setup, employees don't need to worry about it |
| AgentCore Memory | **Admin** | Bound to the Harness, transparent to employees (required) |
| AgentCore Gateway tools | **Admin** | Register enterprise MCP tools, distribute `tools.yaml` template |
| `AWS_REGION` / `AWS_PROFILE` / `HARNESS_ARN` | **Employee** | Fill in `~/.hare/.env`, required for daily use |
| Which remote tools to enable in `tools.yaml` | **Employee** | Edit `~/.hare/tools.yaml`, self-select from the admin-provided tool list |

---

## Part I: Admin Deployment (One-time Setup)

> After completion, share the `HARNESS_ARN` and `tools.yaml` template with employees.

### 1. Prepare Environment

```bash
cd hare
uv sync
cp .env.example .env
# Fill in AWS_REGION, AWS_PROFILE, EXECUTION_ROLE_ARN
```

### 2. Create IAM Execution Role

```bash
uv run python scripts/create_iam_role.py
# Outputs EXECUTION_ROLE_ARN, add to .env
```

Or manually create in AWS Console → IAM → Roles with trust principal `bedrock-agentcore.amazonaws.com` and permissions including `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream`.

### 3. Create Harness

```bash
uv run python scripts/create_harness.py
# Outputs HARNESS_ARN, add to .env and share with employees
```

### 4. Enable Long-term Memory (**Required**)

AgentCore Memory is a core dependency of hare. Without Memory, the Harness cannot maintain context across conversation turns (hare client only sends the current message each time, fully relying on Memory to maintain conversation history on the server side).

```bash
uv run python scripts/create_memory.py
# Automatically creates Memory and binds it to the Harness; employees need no action
```

**How Memory works:**
- **Short-term memory**: Historical messages within the same session, automatically recalled and injected into context
- **Long-term memory**: Key information distilled across sessions (user preferences, project background, etc.), semantically recalled
- The client only sends the current message each turn; the Harness automatically injects relevant memories before inference

### 5. Connect Remote Tools (Optional)

### 5. Enable Browser & Code Interpreter (Recommended)

AgentCore provides built-in Browser and Code Interpreter tools. Once created and bound to the Harness, the AI can browse the web and execute code directly on the server side — no local client changes needed.

```bash
uv run python scripts/create_tools.py
# Creates AgentCore Browser + Code Interpreter resources and binds them to the Harness
```

The AI can then browse the web, run Python/shell code in the server-side microVM, and return results directly — all without touching the local client.

### 6. Connect Remote Tools (Optional)

In AWS Console → AgentCore → Gateways, create a Gateway and register enterprise MCP servers (Jira / ERP / Slack, etc.).

After registration, add the Gateway ARN to the `tools.yaml` template and distribute to employees:

```yaml
gateway_tools:
  - name: jira_tools
    enabled: true
    gateway_arn: arn:aws:bedrock-agentcore:us-west-2:xxx:gateway/yyy
    description: "Jira project management tools"
    auth: awsIam
```

---

## Part II: Employee Setup

> Admin has completed deployment. Employees only need these three steps.

### 1. Install Dependencies

```bash
cd hare && uv sync
```

### 2. Launch

```bash
PYTHONUTF8=1 uv run hare
```

On first launch, hare automatically creates config files in `~/.hare/`:
- `~/.hare/.env` — copied from `.env.example` template, fill in `AWS_REGION`, `AWS_PROFILE`, `HARNESS_ARN`
- `~/.hare/tools.yaml` — copied from `tools.yaml.example` template, enable tools as needed

After filling in `~/.hare/.env`, re-run to start.

---

## Part III: Remote Tools (Optional)

The admin provides a `tools.yaml` template listing registered enterprise tools. Employees enable as needed:

```yaml
# ~/.hare/tools.yaml

local_tools:
  - name: shell_run
    enabled: true
  - name: read_file
    enabled: true
  - name: write_file
    enabled: true

gateway_tools:
  # Select from the admin-provided tool list
  - name: jira_tools
    enabled: true             # Set to true to enable
    gateway_arn: arn:aws:...  # Provided by admin
    description: "Jira project management"
    auth: awsIam
  - name: erp_tools
    enabled: false            # Keep false if not needed
    gateway_arn: arn:aws:...
    description: "ERP system queries"
    auth: awsIam
```

Changes take effect after restarting hare — no redeployment needed.

---

## Built-in Commands

| Command | Description |
|---------|-------------|
| `/clear` | Clear current session history |
| `/session` | Switch / manage sessions (new, delete, rename) |
| `/session list` | List all sessions |
| `/session new <name>` | Create a named session |
| `/cos` | List available personas |
| `/cos <name>` | Switch to a persona (e.g. `/cos catgirl`) |
| `/quit` | Exit |

**Keyboard shortcuts:**
- `↑↓` — Browse history / navigate session picker
- `Esc` — Clear current input
- `Ctrl+C` — Clear input (or quit if empty)
- `→` after `/` — Accept command suggestion

---

## Persona System

Hare supports a multi-persona identity system inspired by [OpenClaw](https://github.com/claw-works). Configuration lives in `~/.hare/`:

| File | Description |
|------|-------------|
| `identity.yaml` | Active persona pointer (`active: hare`) |
| `soul.yaml` | Behavioral core — values, boundaries, language (persists across personas) |
| `companion.yaml` | Info about the human companion (not "master") |
| `personas/*.yaml` | Persona library (each file = one character) |

**Example persona** (`~/.hare/personas/hare.yaml`):
```yaml
name: "Hare"
creature: "Rabbit-type AI assistant"
vibe: "Quiet, reliable, concise"
emoji: "🐇"
tone: "Direct, occasionally humorous"
```

**Self-management:** Hare can autonomously create, update, and switch personas via the built-in `persona_manage` tool. Ask it to "become a catgirl" or "create a pirate persona" and it will handle the rest.

---

## ACP (Agent Communication Protocol)

Hare can delegate coding tasks to local AI coding agents via ACP:

| Agent | Mode | Description |
|-------|------|-------------|
| `claude` | stream-json | Claude Code CLI with structured output |
| `kiro` | print | Kiro CLI (disabled by default) |

Configure in `~/.hare/acp.yaml`. Hare automatically detects installed agents and delegates programming tasks when appropriate.

**How it works:** When you ask Hare to write code or fix bugs, it invokes the coding agent in the specified working directory, parses the structured output, and reports the result.

---

## Local Tools

| Tool | Description |
|------|-------------|
| `local_shell` | Execute shell commands locally, return stdout/stderr |
| `local_read_file` | Read local file contents |
| `local_write_file` | Write to a file (auto-creates directories) |
| `persona_manage` | Self-manage personas (create/update/switch/delete) |
| `coding_agent` | Delegate coding tasks to Claude Code / Kiro |
| `coding_agent_list` | List available coding agents and status |

---

## Supported Regions

AgentCore Harness currently supports (Preview):

| Region | Code |
|--------|------|
| US East (N. Virginia) | `us-east-1` |
| US West (Oregon) | `us-west-2` (recommended) |
| Asia Pacific (Sydney) | `ap-southeast-2` |
| Europe (Frankfurt) | `eu-central-1` |

---

## MCP Support

Hare supports local MCP (Model Context Protocol) servers, compatible with Claude Code / Cursor config format.

Configure in `~/.hare/mcp.json`:
```json
{
  "mcpServers": {
    "my-server": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@some/mcp-server"]
    }
  }
}
```

Supported transports: `stdio`, `sse`, `streamable-http`.

---

## Project Structure

```
hare/
├── hare/
│   ├── main.py            # Entry point
│   ├── harness.py         # Harness client: invoke + streaming + tool loop
│   ├── session.py         # Session persistence (~/.hare/sessions.json)
│   ├── persona.py         # Persona system (identity/soul/companion)
│   ├── summarize.py       # Auto-summarization prompt
│   ├── mcp_client.py      # MCP server manager (stdio/sse/http)
│   ├── tui/
│   │   ├── app.py         # Rich + prompt_toolkit main UI
│   │   ├── session_picker.py  # Session picker with arrow key navigation
│   │   └── confirm.py     # Tool call confirmation dialog
│   └── tools/
│       ├── __init__.py    # Tool registry + execute_tool()
│       ├── config.py      # ~/.hare/tools.yaml loader
│       ├── shell.py       # local_shell
│       ├── filesystem.py  # local_read_file / local_write_file
│       ├── persona_tool.py # persona_manage (self-management)
│       └── acp.py         # ACP: coding agent delegation
├── scripts/
│   ├── create_iam_role.py # Admin: create IAM execution role
│   ├── create_harness.py  # Admin: create Harness resource
│   └── create_memory.py   # Admin: create and bind AgentCore Memory
├── tools.yaml.example     # Template: auto-copied to ~/.hare/tools.yaml on first launch
├── .env.example           # Template: auto-copied to ~/.hare/.env on first launch
└── pyproject.toml
```

---

## Development

```bash
# Adding a new local tool:
# 1. Create a new .py file under hare/tools/
# 2. Register it in hare/tools/__init__.py (TOOL_REGISTRY and TOOL_DEFINITIONS)
# 3. Add the corresponding entry in tools.yaml
```

---

## Session Features

- **Arrow key navigation** in session picker
- **Auto-summarization**: After 3 conversation turns, Hare automatically generates a title and summary (runs in background, doesn't block input)
- **Per-turn stats**: Each response shows elapsed time, token usage (↑input ↓output), and tools called
- **413 error recovery**: If a conversation turn produces oversized content (e.g. base64 images), Hare gracefully recovers instead of crashing

---

## TODO

- [ ] **More convenient authentication**: Currently employees need to configure AWS AKSK (`AWS_PROFILE`), which is not friendly for non-technical users. Planned support for:
  - **Corporate SSO / JWT**: Via AgentCore Harness built-in `customJWTAuthorizer`, employees log in with corporate SSO — no AWS credentials needed
  - **Cognito temporary credentials**: Employees log in via Cognito to obtain temporary AKSK, hare auto-refreshes, transparent to users
  - **Unified gateway proxy**: Enterprise self-hosts a lightweight proxy service holding AKSK, employees only need to configure intranet address and credentials

- [ ] **Windows support**: Currently validated primarily on macOS, Windows terminal compatibility needs testing

- [ ] **Cross-device session sync**: Currently sessions are stored locally at `~/.hare/sessions.json`, plan to support cloud persistence (via AgentCore Memory or S3)

- [ ] **ACP bidirectional streaming**: Full duplex communication with Claude Code via `--input-format stream-json` for multi-turn agent-to-agent collaboration
