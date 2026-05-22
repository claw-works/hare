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

---

## 配置说明

| 配置项 | 负责方 | 说明 |
|--------|--------|------|
| IAM Role + Harness | **运维** | 一次性创建，员工无需关心 |
| AgentCore Memory | **运维** | 绑定在 Harness 上，员工无感知 |
| AgentCore Gateway 工具 | **运维** | 注册企业 MCP 工具，下发 `tools.yaml` 模板 |
| `AWS_REGION` / `AWS_PROFILE` / `HARNESS_ARN` | **员工** | 日常使用必填 |
| `tools.yaml` 中启用哪些远程工具 | **员工** | 从运维提供的工具列表中自选启用 |

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

### 4. 启用长期记忆（可选）

```bash
uv run python scripts/create_memory.py
# 自动创建 Memory 并绑定到 Harness，员工无需任何操作
```

### 5. 接入远端工具（可选）

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

### 2. 配置 .env

```bash
cp .env.example .env
```

编辑 `.env`，只填三项：

```
AWS_REGION=us-west-2
AWS_PROFILE=你的profile名
HARNESS_ARN=<运维提供>
```

### 3. 启动

```bash
PYTHONUTF8=1 uv run hare
```

---

## 三、员工选用远端工具（可选）

运维会提供一份 `tools.yaml` 模板，列出已注册的企业工具。员工按需启用：

```yaml
# tools.yaml（放在项目根目录或 ~/.hare/tools.yaml）

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
| `/quit` | 退出 |

输入 `/` 后按 `→` 接受命令联想；`↑↓` 翻历史；`Ctrl+R` 搜索历史。

---

## 本地工具

| 工具 | 描述 |
|------|------|
| `shell_run` | 在本机执行 shell 命令，返回 stdout/stderr |
| `read_file` | 读取本地文件内容 |
| `write_file` | 写入文件（自动创建目录） |

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

## 项目结构

```
hare/
├── hare/
│   ├── main.py            # 入口
│   ├── harness.py         # Harness 客户端：invoke + streaming + tool loop
│   ├── session.py         # Session 持久化（~/.hare/sessions.json）
│   ├── tui/
│   │   ├── app.py         # Rich + prompt_toolkit 主界面
│   │   └── session_picker.py  # Session 选择器 TUI
│   └── tools/
│       ├── __init__.py    # 工具注册表 + execute_tool()
│       ├── config.py      # tools.yaml 加载
│       ├── shell.py       # shell_run
│       └── filesystem.py  # read_file / write_file
├── scripts/
│   ├── create_iam_role.py # 运维：创建 IAM 执行角色
│   ├── create_harness.py  # 运维：创建 Harness 资源
│   └── create_memory.py   # 运维：创建并绑定 AgentCore Memory
├── tools.yaml             # 员工：工具开关配置（不进 git）
├── .env                   # 员工：环境变量（不进 git）
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
