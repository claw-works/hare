# -*- coding: utf-8 -*-
"""One-time script to create the IAM execution role for Hare Harness."""
import json
import os
import time

import boto3
from dotenv import load_dotenv

# 从 ~/.hare/.env 加载（如果存在）
from pathlib import Path
env_file = Path.home() / ".hare" / ".env"
if env_file.exists():
    load_dotenv(env_file)

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
            "Action": "sts:AssumeRole",
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

    # 附加 AWS 托管策略（覆盖所有 AgentCore 权限：Browser/CodeInterpreter/Gateway/Memory 等）
    managed_policies = [
        "arn:aws:iam::aws:policy/BedrockAgentCoreFullAccess",
        # Memory 存储时需要调用 Bedrock 模型
        "arn:aws:iam::aws:policy/AmazonBedrockAgentCoreMemoryBedrockModelInferenceExecutionRolePolicy",
    ]
    for policy_arn in managed_policies:
        iam.attach_role_policy(RoleName=ROLE_NAME, PolicyArn=policy_arn)
        print(f"✅ 已附加策略: {policy_arn.split('/')[-1]}")

    # 等待 Role 传播（IAM 最终一致性，稍等几秒）
    print(f"⏳ 等待 Role 生效（约 10 秒）...")
    time.sleep(10)

    print(f"\n🎉 IAM Role 就绪！")
    print(f"   ARN: {role_arn}")
    _print_env_hint(role_arn)


def _print_env_hint(role_arn: str):
    print(f"\n请将以下内容写入 ~/.hare/.env：")
    print(f"EXECUTION_ROLE_ARN={role_arn}")


if __name__ == "__main__":
    main()
