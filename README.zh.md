# 🐇 hare

本地 TUI 终端助手，由 Amazon Bedrock AgentCore Harness 驱动。

在终端里打字，AI 在云端推理；本地工具（Shell / 文件系统）在你的机器上执行，企业远端工具（MCP / API）通过 AgentCore Gateway 在云端直接调用。

---

## 架构

```
员工本地机器
┌──────────────────────────────────────┐
│  hare TUI（Rich + prompt_toolkit）   │
│  ├── 用户输入 / 流式输出              │
│  └── 本地工具执行（inline_function） │
│      shell_run / read_file / write_file │
└─────────────────┬────────────────────┘
                  │ InvokeHarness (boto3 streaming)
                  ▼
云端 AWS（运维统一管理）
┌──────────────────────────────────────────────────────┐
│  AgentCore Harness                                    │
│  ├── 模型推理（Claude / GPT / Gemini）               │
│  ├── Agent Loop（工具路由、多轮推理）                │
│  ├── 长期记忆（AgentCore Memory，运维绑定）          │
│  └── 工具路由                                        │
│      ├── inline_function → 返回本地执行              │
│      └── agentcore_gateway → 调企业 MCP server       │
│          （Jira / ERP / Slack 等，运维注册）         │
└──────────────────────────────────────────────────────┘
```

### 长期记忆（AgentCore Memory）

Harness 在每轮对话中自动做两件事：

1. **召回**：推理开始前，从 Memory 中检索与当前问题相关的历史记忆，自动注入上下文
2. **写入**：对话结束后，将重要信息提炼并存入 Memory，供下次会话使用

记忆由运维在 Harness 层绑定，员工无感知——不需要额外配置，重启 hare 后仍能记住你上次说的事。

---

## 配置说明

| 配置项 | 负责方 | 说明 |
|--------|--------|------|
| IAM Role + Harness | **运维** | 一次性创建，员工无需关心 |
| AgentCore Memory | **运维** | 绑定在 Harness 上，员工无感知（必须启用） |
| AgentCore Gateway 工具 | **运维** | 注册企业 MCP 工具，下发 `tools.yaml` 模板 |
| `AWS_REGION` / `AWS_PROFILE` / `HARNESS_ARN` | **员工** | 填入 `~/.hare/.env`，日常使用必填 |
| `tools.yaml` 中启用哪些远程工具 | **员工** | 编辑 `~/.hare/tools.yaml`，从运维提供的工具列表中自选启用 |

---

## 一、运维部署（管理员一次性操作）

> 执行完后，把 `HARNESS_ARN` 和 `tools.yaml` 模板告知员工即可。

### 1. 准备环境

```bash
cd hare
uv sync
cp .env.example .env
# 填入 AWS_REGION、AWS_PROFILE、EXECUTION_ROLE_ARN
```

### 2. 创建 IAM 执行角色

```bash
uv run python scripts/create_iam_role.py
# 输出 EXECUTION_ROLE_ARN，填入 .env
```

或手动在 AWS Console → IAM → Roles 创建，信任主体为 `bedrock-agentcore.amazonaws.com`，权限包含 `bedrock:InvokeModel` 和 `bedrock:InvokeModelWithResponseStream`。

### 3. 创建 Harness

```bash
uv run python scripts/create_harness.py
# 输出 HARNESS_ARN，填入 .env，并告知员工
```

### 4. 启用长期记忆（**必须**）

AgentCore Memory 是 hare 的核心依赖。没有 Memory，Harness 无法在多轮对话中保持上下文（hare 客户端每次只传当前消息，完全依赖 Memory 在服务端维护对话历史）。

```bash
uv run python scripts/create_memory.py
# 自动创建 Memory 并绑定到 Harness，员工无需任何操作
```

**Memory 工作原理：**
- **短期记忆**：同一 session 内的历史消息，自动召回注入上下文
- **长期记忆**：跨 session 提炼的关键信息（用户偏好、项目背景等），语义召回
- 客户端每次只传当前这轮消息，Harness 在推理前自动注入相关记忆

### 5. 启用 Browser 和 Code Interpreter（推荐）

AgentCore 提供内置的浏览器工具和代码解释器工具。创建并绑定到 Harness 后，AI 可以直接在服务端浏览网页、执行代码——本地客户端无需任何改动。

```bash
uv run python scripts/create_tools.py
# 自动创建 Browser + Code Interpreter 资源并绑定到 Harness
```

绑定后 AI 可以：浏览网页获取实时信息、在服务端 microVM 里运行 Python/Shell 代码、直接返回执行结果。完全在云端发生，本地无感知。

### 6. 接入远端工具（可选）

在 AWS Console → AgentCore → Gateways 创建 Gateway，注册企业 MCP server（Jira / ERP / Slack 等）。

注册完成后，把 Gateway ARN 写入 `tools.yaml` 模板下发给员工：

```yaml
gateway_tools:
  - name: jira_tools
    enabled: true
    gateway_arn: arn:aws:bedrock-agentcore:us-west-2:xxx:gateway/yyy
    description: "Jira 项目管理工具"
    auth: awsIam
```

---

## 二、员工使用

> 运维已部署完成，员工只需以下三步。

### 1. 安装依赖

```bash
cd hare && uv sync
```

### 2. 启动

```bash
PYTHONUTF8=1 uv run hare
```

首次启动时，hare 会自动在 `~/.hare/` 创建配置文件：
- `~/.hare/.env` — 从 `.env.example` 模板拷贝，需填入 `AWS_REGION`、`AWS_PROFILE`、`HARNESS_ARN`
- `~/.hare/tools.yaml` — 从 `tools.yaml.example` 模板拷贝，可按需启用工具

填写完 `~/.hare/.env` 后重新运行即可。

---

## 三、员工选用远端工具（可选）

运维会提供一份 `tools.yaml` 模板，列出已注册的企业工具。员工按需启用：

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
  # 从运维提供的工具列表中选择启用
  - name: jira_tools
    enabled: true             # 改为 true 即启用
    gateway_arn: arn:aws:...  # 运维提供
    description: "Jira 项目管理"
    auth: awsIam
  - name: erp_tools
    enabled: false            # 不需要就保持 false
    gateway_arn: arn:aws:...
    description: "ERP 系统查询"
    auth: awsIam
```

修改后重启 hare 即生效，无需重新部署。

---

## 内置命令

| 命令 | 说明 |
|------|------|
| `/clear` | 清空当前会话历史 |
| `/session` | 切换 / 管理会话（新建、删除、重命名） |
| `/session list` | 列出所有会话 |
| `/session new <名称>` | 新建命名会话 |
| `/cos` | 列出可用人设 |
| `/cos <名称>` | 切换人设（如 `/cos catgirl`） |
| `/quit` | 退出 |

**快捷键：**
- `↑↓` — 翻历史 / 会话选择器导航
- `Esc` — 清除当前输入
- `Ctrl+C` — 清除输入（输入为空时退出）
- `/` 后按 `→` — 接受命令联想

---

## 人设系统

Hare 支持多人格身份系统，设计灵感来自 [OpenClaw](https://github.com/claw-works)。配置存于 `~/.hare/`：

| 文件 | 说明 |
|------|------|
| `identity.yaml` | 当前激活人格指针（`active: hare`） |
| `soul.yaml` | 行为灵魂 — 价值观、边界、语言（跨人格不变） |
| `companion.yaml` | 人类同伴信息（不是"主人"） |
| `personas/*.yaml` | 人格库（每个文件 = 一个角色） |

**示例人格**（`~/.hare/personas/hare.yaml`）：
```yaml
name: "Hare"
creature: "兔系 AI 助手"
vibe: "安静可靠，话不多但管用"
emoji: "🐇"
tone: "简洁直接，偶尔幽默"
```

**自治能力：** Hare 可以通过内置 `persona_manage` 工具自主创建、修改、切换人格。对它说"变成猫娘"或"帮我加一个海盗角色"，它会自己搞定。

---

## ACP（Agent 通信协议）

Hare 可以将编程任务委派给本地 AI coding agent：

| Agent | 模式 | 说明 |
|-------|------|------|
| `claude` | stream-json | Claude Code CLI，结构化输出 |
| `kiro` | print | Kiro CLI（默认关闭） |

配置在 `~/.hare/acp.yaml`。Hare 自动检测已安装的 agent，在需要编程时自动委派任务。

**工作方式：** 当你让 Hare 写代码或修 bug 时，它会在指定工作目录调用 coding agent，解析结构化输出后汇报结果。

---

## Sub-Agent（子任务）

Hare 可以在同一个 Harness 上启动独立子任务：

- `sub_task` 工具 — 启动子会话，短期记忆隔离，长期记忆共享
- 子会话 ID 以 `hsub_` 开头，不会出现在会话列表中
- 适用于查资料、做计算、翻译等不需要当前上下文的独立任务

Session ID 命名约定（为未来多端同步准备）：

| 模式 | 含义 | 同步策略 |
|------|------|---------|
| `h` + 36位 | 主会话 | 拉到本地 |
| `hsub_` + 前缀 + uuid | 子任务 | 忽略 |
| `*_r` 结尾 | 修复派生 | 跟随主会话 |

---

## 本地工具

| 工具 | 描述 |
|------|------|
| `local_shell` | 在本机执行 shell 命令，返回 stdout/stderr |
| `local_read_file` | 读取本地文件内容 |
| `local_write_file` | 写入文件（自动创建目录） |
| `persona_manage` | 自主管理人格（创建/更新/切换/删除） |
| `coding_agent` | 委派编程任务给 Claude Code / Kiro |
| `coding_agent_list` | 列出可用 coding agent 及状态 |
| `sub_task` | 启动独立子任务（隔离上下文，共享长期记忆） |

---

## 支持区域

AgentCore Harness 目前（Preview）支持：

| 区域 | 代码 |
|------|------|
| 美国东部（弗吉尼亚北部）| `us-east-1` |
| 美国西部（俄勒冈）| `us-west-2`（推荐）|
| 亚太（悉尼）| `ap-southeast-2` |
| 欧洲（法兰克福）| `eu-central-1` |

---

## MCP 支持

Hare 支持本地 MCP（Model Context Protocol）server，兼容 Claude Code / Cursor 的配置格式。

配置 `~/.hare/mcp.json`：
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

支持传输方式：`stdio`、`sse`、`streamable-http`。

---

## 项目结构

```
hare/
├── hare/
│   ├── main.py            # 入口
│   ├── harness.py         # Harness 客户端：invoke + streaming + tool loop
│   ├── session.py         # Session 持久化（~/.hare/sessions.json）
│   ├── persona.py         # 人设系统（identity/soul/companion）
│   ├── summarize.py       # 自动摘要 prompt
│   ├── mcp_client.py      # MCP server 管理器（stdio/sse/http）
│   ├── tui/
│   │   ├── app.py         # Rich + prompt_toolkit 主界面
│   │   ├── session_picker.py  # 会话选择器（支持方向键导航）
│   │   └── confirm.py     # 工具调用确认对话框
│   └── tools/
│       ├── __init__.py    # 工具注册表 + execute_tool()
│       ├── config.py      # ~/.hare/tools.yaml 加载
│       ├── shell.py       # local_shell
│       ├── filesystem.py  # local_read_file / local_write_file
│       ├── persona_tool.py # persona_manage（自治管理）
│       ├── acp.py         # ACP：coding agent 委派
│       └── sub_agent.py   # sub_task：子任务 agent
├── scripts/
│   ├── create_iam_role.py # 运维：创建 IAM 执行角色
│   ├── create_harness.py  # 运维：创建 Harness 资源
│   └── create_memory.py   # 运维：创建并绑定 AgentCore Memory
├── tools.yaml.example     # 模板：首次启动自动拷贝到 ~/.hare/tools.yaml
├── .env.example           # 模板：首次启动自动拷贝到 ~/.hare/.env
└── pyproject.toml
```

---

## 开发

```bash
# 添加新本地工具：
# 1. 在 hare/tools/ 下新建 .py 文件
# 2. 在 hare/tools/__init__.py 注册到 TOOL_REGISTRY 和 TOOL_DEFINITIONS
# 3. 在 tools.yaml 中添加对应条目
```

---

## 会话功能

- **方向键导航** — 会话选择器支持 ↑↓ 选择
- **搜索** — 选择器中输入 `/` 按名称/摘要过滤
- **会话回顾** — 进入/切换会话时显示一句话上次摘要（"📝 上次: ..."）
- **自动摘要** — 第 3 轮首次生成，之后每 5 轮更新（后台运行，不阻塞输入）
- **轮次统计** — 每次回复后显示耗时、token 用量（↑输入 ↓输出）、工具调用摘要
- **错误恢复** — 413 超限和 Memory 损坏均自动恢复（派生新 session ID 绕过）

---

## TODO

- [ ] **更便捷的认证方式**：当前需要员工配置 AWS AKSK（`AWS_PROFILE`），对非技术人员不友好。计划支持以下认证方式：
  - **公司 SSO / JWT**：通过 AgentCore Harness 内置的 `customJWTAuthorizer`，员工用公司 SSO 登录即可，无需 AWS 凭证
  - **Cognito 临时凭证**：员工通过 Cognito 登录换取临时 AKSK，hare 自动刷新，用户无感知
  - **统一网关代理**：企业自建轻量代理服务持有 AKSK，员工只需配置内网地址和工号密码

- [ ] **Windows 支持**：当前主要在 macOS 验证，Windows 终端兼容性待测试

- [ ] **会话跨设备同步**：当前 session 存储在本地 `~/.hare/sessions.json`，支持云端持久化（利用 AgentCore Memory 或 S3）

- [ ] **ACP 双向流**：与 Claude Code 通过 `--input-format stream-json` 做全双工通信，实现 agent 间多轮协作