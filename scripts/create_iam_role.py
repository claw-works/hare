"""One-time script to create the IAM execution role for Hare Harness."""
import json
import os
import time

import boto3
from dotenv import load_dotenv

load_dotenv()

ROLE_NAME = "hare-harness-execution-role"
REGION = os.environ.get("AWS_REGION", "us-west-2")
PROFILE = os.environ.get("AWS_PROFILE")

TRUST_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "bedrock-agentcore.amazonaws.com"
            },
        {
            "Effect": "Allow",
            "Action": [
                "bedrock-agentcore:ListEvents",
                "bedrock-agentcore:GetMemory",
                "bedrock-agentcore:CreateEvent",
                "bedrock-agentcore:InvokeMemory",
                "bedrock-agentcore:RetrieveMemoryRecords",
            ],
            "Resource": "arn:aws:bedrock-agentcore:*:*:memory/*",
        {
            # Browser 工具所需权限
            "Effect": "Allow",
            "Action": [
                "bedrock-agentcore:InvokeBrowser",
            ],
            "Resource": "*",
        },
        {
            # Code Interpreter 工具所需权限
            "Effect": "Allow",
            "Action": [
                "bedrock-agentcore:InvokeCodeInterpreter",
            ],
            "Resource": "*",
        },
        {
            # Gateway 工具所需权限（可选，接入企业 MCP server 时需要）
            "Effect": "Allow",
            "Action": [
                "bedrock-agentcore:InvokeGateway",
            ],
            "Resource": "*",
        },
        },
            "Action": "sts:AssumeRole",
        }
    ],
}

INLINE_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
            ],
            "Resource": "*",
        }
    ],
}


def main():
    session = boto3.Session(region_name=REGION, profile_name=PROFILE)
    iam = session.client("iam")

    # 检查 Role 是否已存在
    try:
        existing = iam.get_role(RoleName=ROLE_NAME)
        role_arn = existing["Role"]["Arn"]
        print(f"✅ IAM Role 已存在，跳过创建：")
        print(f"   ARN: {role_arn}")
        _print_env_hint(role_arn)
        return
    except iam.exceptions.NoSuchEntityException:
        pass

    # 创建 Role
    print(f"⏳ 正在创建 IAM Role: {ROLE_NAME} ...")
    resp = iam.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps(TRUST_POLICY),
        Description="Execution role for Hare AgentCore Harness",
    )
    role_arn = resp["Role"]["Arn"]
    print(f"✅ Role 创建成功")

    # 附加内联权限策略
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="hare-bedrock-invoke",
        PolicyDocument=json.dumps(INLINE_POLICY),
    )
    print(f"✅ 权限策略已附加")

    # 等待 Role 传播（IAM 最终一致性，稍等几秒）
    print(f"⏳ 等待 Role 生效（约 10 秒）...")
    time.sleep(10)

    print(f"\n🎉 IAM Role 就绪！")
    print(f"   ARN: {role_arn}")
    _print_env_hint(role_arn)


def _print_env_hint(role_arn: str):
    print(f"\n请将以下内容写入 .env：")
    print(f"EXECUTION_ROLE_ARN={role_arn}")


if __name__ == "__main__":
    main()
