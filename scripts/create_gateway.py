# -*- coding: utf-8 -*-
"""Create AgentCore Gateway and register MCP servers (ops script).

Gateway is AgentCore's unified enterprise tool access layer:
- Register any MCP server (HTTP/SSE/Stdio)
- Unified auth management (AWS IAM / OAuth / JWT)
- After creation, write gatewayArn to ~/.hare/tools.yaml for distribution

Notes:
- Browser and Code Interpreter don't need resource creation, just declare in invoke_harness tools
- Gateway requires creation to obtain ARN, then users configure it in tools.yaml
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
    """Create a Gateway connecting to a remote MCP server, return gatewayArn."""
    print(f"⏳ Creating Gateway: {name} → {mcp_url}")
    resp = client.create_gateway(
        name=name,
        description=description or f"Gateway for {name}",
        protocolType="MCP",
        authorizerType="AWS_IAM",   # Use AWS IAM for access control
        protocolConfiguration={
            "mcp": {
                "searchType": "SEMANTIC",
            }
        },
    )
    print(f"   create_gateway response fields: {list(resp.keys())}")
    inner = resp.get("gateway") or resp
    gateway_id = inner.get("gatewayId") or inner.get("id")
    gateway_arn = inner.get("gatewayArn") or inner.get("arn")
    print(f"   ID: {gateway_id}")

    # Wait for READY
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
            raise RuntimeError(f"Gateway creation failed: {status}")

    print(f"✅ Gateway ARN: {gateway_arn}")
    return gateway_arn


def create_gateway_target(client, gateway_id: str, mcp_url: str, name: str) -> None:
    """Register a MCP server target for the Gateway."""
    print(f"⏳ Registering MCP server: {mcp_url}")
    resp = client.create_gateway_target(
        gatewayId=gateway_id,
        name=name,
        endpoint={
            "mcpServer": {
                "url": mcp_url,
            }
        },
    )
    print(f"✅ Target registered: {resp.get('targetId') or resp.get('gatewayTargetId', '?')}")


def main():
    """Example: create a Gateway connecting to a MCP server.

    In practice, modify the MCP_SERVERS list to specify your remote MCP servers.
    """
    # MCP servers to connect
    # Each entry: (gateway_name, mcp_url, description)
    MCP_SERVERS = [
        # Example: connect to public MCP server
        # ("exa-search", "https://mcp.exa.ai/mcp", "Exa AI search tool"),
        # Example: connect to internal API
        # ("internal-api", "https://api.company.com/mcp", "Internal enterprise API"),
    ]

    if not MCP_SERVERS:
        print("⚠️  Please configure MCP servers in the MCP_SERVERS list")
        print("   Example:")
        print('   MCP_SERVERS = [("exa-search", "https://mcp.exa.ai/mcp", "Exa Search")]')
        print()
        print("After creating Gateway, write gatewayArn to ~/.hare/tools.yaml:")
        print("""
gateway_tools:
  - name: my_gateway
    enabled: true
    gateway_arn: arn:aws:bedrock-agentcore:us-west-2:xxx:gateway/yyy
    description: "My enterprise tools"
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

    print("\n🎉 All Gateways created!")
    print("\nAdd the following to the gateway_tools list in ~/.hare/tools.yaml:")
    for name, arn in results:
        print(f"""
  - name: {name}
    enabled: true
    gateway_arn: {arn}
    description: ""
    auth: awsIam""")

    print("\nNote:")
    print("  - Browser and Code Interpreter don't need resource creation, hare declares them automatically")
    print("  - Only Gateway requires the ARN from here")


if __name__ == "__main__":
    main()
