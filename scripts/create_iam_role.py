# -*- coding: utf-8 -*-
"""One-time script to create the IAM execution role for Hare Harness."""
import json
import os
import time

import boto3
from dotenv import load_dotenv

# Load from ~/.hare/.env if it exists
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

    # Check if Role already exists
    try:
        existing = iam.get_role(RoleName=ROLE_NAME)
        role_arn = existing["Role"]["Arn"]
        print(f"✅ IAM Role already exists, skipping creation:")
        print(f"   ARN: {role_arn}")
        _print_env_hint(role_arn)
        return
    except iam.exceptions.NoSuchEntityException:
        pass

    # Create Role
    print(f"⏳ Creating IAM Role: {ROLE_NAME} ...")
    resp = iam.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps(TRUST_POLICY),
        Description="Execution role for Hare AgentCore Harness",
    )
    role_arn = resp["Role"]["Arn"]
    print(f"✅ Role created successfully")

    # Attach AWS managed policies (covers all AgentCore permissions: Browser/CodeInterpreter/Gateway/Memory etc.)
    managed_policies = [
        "arn:aws:iam::aws:policy/BedrockAgentCoreFullAccess",
        # Memory storage requires Bedrock model invocation
        "arn:aws:iam::aws:policy/AmazonBedrockAgentCoreMemoryBedrockModelInferenceExecutionRolePolicy",
    ]
    for policy_arn in managed_policies:
        iam.attach_role_policy(RoleName=ROLE_NAME, PolicyArn=policy_arn)
        print(f"✅ Attached policy: {policy_arn.split('/')[-1]}")

    # Wait for Role propagation (IAM eventual consistency)
    print(f"⏳ Waiting for Role to propagate (~10s)...")
    time.sleep(10)

    print(f"\n🎉 IAM Role ready!")
    print(f"   ARN: {role_arn}")
    _print_env_hint(role_arn)


def _print_env_hint(role_arn: str):
    print(f"\nWrite the following to ~/.hare/.env:")
    print(f"EXECUTION_ROLE_ARN={role_arn}")


if __name__ == "__main__":
    main()
