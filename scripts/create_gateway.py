# -*- coding: utf-8 -*-
"""创建 AgentCore Gateway 并注册 MCP server（运维脚本）。

Gateway 是 AgentCore 的企业工具统一接入层：
- 支持注册任意 MCP server（HTTP/SSE/Stdio）
- 统一权限管理（AWS IAM / OAuth / JWT）
- 完成后将 gatewayArn 写入 ~/.hare/tools.yaml 下发给员工

注意：
- Browser 和 Code Interpreter 不需要创建资源，直接在 invoke_harness 的 tools 里声明即可
- Gateway 才需要先创建获取 ARN，然后员工在 tools.yaml 里配置
"""
import json
import os
import time

import boto3
from pathlib import Path
from dotenv import load_dotenv

env_file = Path.home() / ".hare" / ".env"
if env_file.exists():
    load_dotenv(env_file)

REGION = os.environ.get("AWS_REGION", "us-west-2")
PROFILE = os.environ.get("AWS_PROFILE")


def create_gateway(client, name: str, mcp_url: str, description: str = "") -> str:
    """创建一个接入远端 MCP server 的 Gateway，返回 gatewayArn。"""
    print(f"⏳ 创建 Gateway: {name} → {mcp_url}")
    resp = client.create_gateway(
        name=name,
        description=description or f"Gateway for {name}",
        protocolType="MCP",
        authorizerType="AWS_IAM",   # 用 AWS IAM 控制调用权限
        protocolConfiguration={
            "mcp": {
                "searchType": "SEMANTIC",
            }
        },
    )
    print(f"   create_gateway 返回字段: {list(resp.keys())}")
    inner = resp.get("gateway") or resp
    gateway_id = inner.get("gatewayId") or inner.get("id")
    gateway_arn = inner.get("gatewayArn") or inner.get("arn")
    print(f"   ID: {gateway_id}")

    # 等待 READY
    for i in range(30):
        time.sleep(3)
        detail = client.get_gateway(gatewayId=gateway_id)
        inner_d = detail.get("gateway") or detail
        status = inner_d.get("status", "UNKNOWN")
        print(f"   [{i*3}s] status: {status}")
        if status == "READY":
            gateway_arn = inner_d.get("gatewayArn") or gateway_arn
            break
        elif status in ("FAILED", "DELETED"):
            raise RuntimeError(f"Gateway 创建失败: {status}")

    print(f"✅ Gateway ARN: {gateway_arn}")
    return gateway_arn


def create_gateway_target(client, gateway_id: str, mcp_url: str, name: str) -> None:
    """为 Gateway 注册一个 MCP server target。"""
    print(f"⏳ 注册 MCP server: {mcp_url}")
    resp = client.create_gateway_target(
        gatewayId=gateway_id,
        name=name,
        endpoint={
            "mcpServer": {
                "url": mcp_url,
            }
        },
    )
    print(f"✅ Target 已注册: {resp.get('targetId') or resp.get('gatewayTargetId', '?')}")


def main():
    """示例：创建一个连接本地 MCP server 的 Gateway。
    
    实际使用时修改 MCP_SERVERS 列表，指定你要接入的远端 MCP server。
    """
    # 配置要接入的 MCP servers
    # 每个条目: (gateway_name, mcp_url, description)
    MCP_SERVERS = [
        # 示例：接入公共 MCP server
        # ("exa-search", "https://mcp.exa.ai/mcp", "Exa AI 搜索工具"),
        # 示例：接入内部 API
        # ("internal-api", "https://api.company.com/mcp", "企业内部 API"),
    ]

    if not MCP_SERVERS:
        print("⚠️  请在 MCP_SERVERS 列表中配置要接入的 MCP server")
        print("   示例:")
        print('   MCP_SERVERS = [("exa-search", "https://mcp.exa.ai/mcp", "Exa 搜索")]')
        print()
        print("创建 Gateway 后，将 gatewayArn 写入 ~/.hare/tools.yaml：")
        print("""
gateway_tools:
  - name: my_gateway
    enabled: true
    gateway_arn: arn:aws:bedrock-agentcore:us-west-2:xxx:gateway/yyy
    description: "我的企业工具"
    auth: awsIam
""")
        return

    session = boto3.Session(region_name=REGION, profile_name=PROFILE)
    client = session.client("bedrock-agentcore-control")

    results = []
    for gateway_name, mcp_url, description in MCP_SERVERS:
        gateway_arn = create_gateway(client, gateway_name, mcp_url, description)
        gateway_id = gateway_arn.split("/")[-1]
        create_gateway_target(client, gateway_id, mcp_url, f"{gateway_name}_target")
        results.append((gateway_name, gateway_arn))

    print("\n🎉 所有 Gateway 创建完成！")
    print("\n请将以下内容加入 ~/.hare/tools.yaml 的 gateway_tools 列表：")
    for name, arn in results:
        print(f"""
  - name: {name}
    enabled: true
    gateway_arn: {arn}
    description: ""
    auth: awsIam""")

    print("\n注意：")
    print("  - Browser 和 Code Interpreter 不需要创建资源，hare 会自动声明")
    print("  - Gateway 才需要这里的 ARN")


if __name__ == "__main__":
    main()
