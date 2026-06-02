# -*- coding: utf-8 -*-
"""Create AgentCore Memory and bind to Harness."""
import json, os, time
import boto3
from dotenv import load_dotenv
load_dotenv()

REGION = os.environ.get("AWS_REGION", "us-west-2")
PROFILE = os.environ.get("AWS_PROFILE")
HARNESS_ARN = os.environ["HARNESS_ARN"]
MEMORY_NAME = "hare_memory"


def main():
    session = boto3.Session(region_name=REGION, profile_name=PROFILE)
    client = session.client("bedrock-agentcore-control")

    # 1. List existing Memory, find hare_memory (id starts with hare_memory-)
    print("🔍 Looking for existing Memory...")
    list_resp = client.list_memories()
    memories = list_resp.get("memories") or []

    # list_memories returns id/arn/status fields, no name field
    # hare_memory id = "hare_memory-<random_suffix>" when created
    existing = next(
        (m for m in memories if m.get("id", "").startswith(MEMORY_NAME)),
        None
    )

    if existing:
        memory_arn = existing["arn"]
        memory_id = existing["id"]
        status = existing.get("status", "")
        print(f"✅ Memory already exists: {memory_id} (status: {status})")

        # If still CREATING, wait until ACTIVE
        if status != "ACTIVE":
            print(f"⏳ Waiting for Memory to become ACTIVE...")
            for i in range(30):
                time.sleep(3)
                detail = client.get_memory(memoryId=memory_id)
                inner = detail.get("memory") or detail
                status = inner.get("status", "UNKNOWN")
                print(f"   [{i*3}s] status: {status}")
                if status == "ACTIVE":
                    break
                elif status in ("FAILED", "DELETED"):
                    print(f"❌ Memory status abnormal: {status}")
                    return
    else:
        # Create new Memory
        print(f"⏳ Creating AgentCore Memory '{MEMORY_NAME}'...")
        resp = client.create_memory(
            name=MEMORY_NAME,
            description="Hare assistant long-term memory",
            eventExpiryDuration=90,
        )
        inner = resp.get("memory") or resp
        memory_arn = inner.get("arn") or inner.get("memoryArn")
        memory_id = inner.get("id") or inner.get("memoryId")
        print(f"   ARN: {memory_arn}, ID: {memory_id}")

        print(f"⏳ Waiting for Memory ACTIVE...")
        for i in range(30):
            time.sleep(3)
            detail = client.get_memory(memoryId=memory_id)
            inner_d = detail.get("memory") or detail
            status = inner_d.get("status", "UNKNOWN")
            print(f"   [{i*3}s] status: {status}")
            if status == "ACTIVE":
                break
            elif status in ("FAILED", "DELETED"):
                print(f"❌ Memory creation failed: {status}")
                return

    # 2. update_harness to bind memory
    harness_id = HARNESS_ARN.split("/")[-1]
    print(f"\n⏳ Binding Memory to Harness ({harness_id})...")
    client.update_harness(
        harnessId=harness_id,
        memory={
            "optionalValue": {
                "agentCoreMemoryConfiguration": {
                    "arn": memory_arn,
                    "messagesCount": 20,   # No actorId, Harness uses session-level default isolation
                }
            }
        }
    )
    print(f"\n🎉 Memory bound to Harness!")
    print(f"\nWrite the following to .env:")
    print(f"MEMORY_ARN={memory_arn}")


if __name__ == "__main__":
    main()
