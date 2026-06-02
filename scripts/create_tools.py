# -*- coding: utf-8 -*-
"""AgentCore Tools README:

Browser and Code Interpreter don't need resource creation — just declare in invoke_harness tools param:
  {"type": "agentcore_browser", "name": "browser"}
  {"type": "agentcore_code_interpreter", "name": "code_interpreter"}

hare's harness.py already includes both tools in _build_all_tools() by default, no extra steps needed.

For custom versions (VPC config, recording, etc. enterprise features), see AWS docs:
  https://docs.aws.amazon.com/botocore/latest/reference/services/bedrock-agentcore-control/client/create_browser.html
  https://docs.aws.amazon.com/botocore/latest/reference/services/bedrock-agentcore-control/client/create_code_interpreter.html

Gateway must be created first, see scripts/create_gateway.py.

This script is a placeholder — extend here if enterprise-grade custom Browser/Code Interpreter is needed later.
"""

if __name__ == "__main__":
    print(__doc__)
