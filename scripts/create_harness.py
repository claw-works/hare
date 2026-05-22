"""One-time script to create a Harness resource on AWS."""
import json, os, time
import boto3
from dotenv import load_dotenv

load_dotenv()

REGION = os.environ.get("AWS_REGION", "us-west-2")
PROFILE = os.environ.get("AWS_PROFILE")
EXECUTION_ROLE_ARN = os.environ.get("EXECUTION_ROLE_ARN")

def main():
    if not EXECUTION_ROLE_ARN:
        print("❌ 请在 .env 中设置 EXECUTION_ROLE_ARN")
        print("   格式：arn:aws:iam::ACCOUNT_ID:role/ROLE_NAME")
        return

    session = boto3.Session(region_name=REGION, profile_name=PROFILE)
    client = session.client("bedrock-agentcore-control")

    print(f"⏳ 正在创建 Harness (region: {REGION})...")
    resp = client.create_harness(
        harnessName="hare_assistant",
        executionRoleArn=EXECUTION_ROLE_ARN,
    )

    harness_id = resp.get("harnessId") or resp.get("harness", {}).get("harnessId")
    harness_arn = resp.get("harnessArn") or resp.get("harness", {}).get("harnessArn")
    print(f"✅ Harness 创建请求已提交")
    print(f"   Response keys: {list(resp.keys())}")  # 临时调试，确认返回字段名
    print(f"✅ Harness 创建成功，ID: {harness_id}")
    print(f"   等待 READY 状态...")

    # 轮询等待 READY
    for i in range(150):
        time.sleep(2)
        detail = client.get_harness(harnessId=harness_id)
        status = detail.get("status", "UNKNOWN")
        print(f"   [{i*2}s] status: {status}")
        if status == "READY":
            print(f"\n🎉 Harness 就绪！")
            print(f"\n请将以下内容写入 .env：")
            print(f"HARNESS_ARN={harness_arn}")
            return
        elif status in ("FAILED", "DELETED"):
            print(f"❌ Harness 创建失败，status: {status}")
            print(json.dumps(detail, indent=2, default=str))
            return

    print("⚠️ 超时，请手动检查：")
    print(f"HARNESS_ARN={harness_arn}")

if __name__ == "__main__":
    main()
