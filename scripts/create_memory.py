# -*- coding: utf-8 -*-
"""创建 AgentCore Memory 并绑定到 Harness。"""
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

    # 1. 列出已有 Memory，找到 hare_memory（id 以 hare_memory- 开头）
    print("🔍 查找已有 Memory...")
    list_resp = client.list_memories()
    memories = list_resp.get("memories") or []
    
    # list_memories 返回的字段是 id/arn/status，没有 name 字段
    # hare_memory 创建时 id = "hare_memory-<随机后缀>"
    existing = next(
        (m for m in memories if m.get("id", "").startswith(MEMORY_NAME)),
        None
    )

    if existing:
        memory_arn = existing["arn"]
        memory_id = existing["id"]
        status = existing.get("status", "")
        print(f"✅ Memory 已存在: {memory_id} (status: {status})")

        # 如果还在 CREATING，等待变成 ACTIVE
        if status != "ACTIVE":
            print(f"⏳ 等待 Memory 变为 ACTIVE...")
            for i in range(30):
                time.sleep(3)
                detail = client.get_memory(memoryId=memory_id)
                inner = detail.get("memory") or detail
                status = inner.get("status", "UNKNOWN")
                print(f"   [{i*3}s] status: {status}")
                if status == "ACTIVE":
                    break
                elif status in ("FAILED", "DELETED"):
                    print(f"❌ Memory 状态异常: {status}")
                    return
    else:
        # 创建新 Memory
        print(f"⏳ 创建 AgentCore Memory '{MEMORY_NAME}'...")
        resp = client.create_memory(
            name=MEMORY_NAME,
            description="Hare assistant long-term memory",
            eventExpiryDuration=90,
        )
        inner = resp.get("memory") or resp
        memory_arn = inner.get("arn") or inner.get("memoryArn")
        memory_id = inner.get("id") or inner.get("memoryId")
        print(f"   ARN: {memory_arn}, ID: {memory_id}")

        print(f"⏳ 等待 Memory ACTIVE...")
        for i in range(30):
            time.sleep(3)
            detail = client.get_memory(memoryId=memory_id)
            inner_d = detail.get("memory") or detail
            status = inner_d.get("status", "UNKNOWN")
            print(f"   [{i*3}s] status: {status}")
            if status == "ACTIVE":
                break
            elif status in ("FAILED", "DELETED"):
                print(f"❌ Memory 创建失败: {status}")
                return

    # 2. update_harness 绑定 memory
    harness_id = HARNESS_ARN.split("/")[-1]
    print(f"\n⏳ 绑定 Memory 到 Harness ({harness_id})...")
    client.update_harness(
        harnessId=harness_id,
        memory={
            "optionalValue": {
                "agentCoreMemoryConfiguration": {
                    "arn": memory_arn,
                    "actorId": "$session",
                    "messagesCount": 20,
                }
            }
        }
    )
    print(f"\n🎉 Memory 已绑定到 Harness！")
    print(f"\n请将以下内容写入 .env：")
    print(f"MEMORY_ARN={memory_arn}")


if __name__ == "__main__":
    main()
