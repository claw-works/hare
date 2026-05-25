# -*- coding: utf-8 -*-
"""AgentCore 工具说明：

Browser 和 Code Interpreter 无需创建资源，直接在 invoke_harness 的 tools 参数里声明即可：
  {"type": "agentcore_browser", "name": "browser"}
  {"type": "agentcore_code_interpreter", "name": "code_interpreter"}

hare 的 harness.py 已默认在 _build_all_tools() 里包含这两个工具，无需额外操作。

如需创建"自定义"版本（配置 VPC、录制等企业级功能），参考 AWS 文档：
  https://docs.aws.amazon.com/botocore/latest/reference/services/bedrock-agentcore-control/client/create_browser.html
  https://docs.aws.amazon.com/botocore/latest/reference/services/bedrock-agentcore-control/client/create_code_interpreter.html

Gateway 则必须先创建，参见 scripts/create_gateway.py。

此脚本暂时为占位说明，后续如需企业级自定义 Browser/Code Interpreter 可在此扩展。
"""

if __name__ == "__main__":
    print(__doc__)
