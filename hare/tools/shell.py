import subprocess
from typing import Any


def shell_run(command: str, working_dir: str = ".") -> dict[str, Any]:
    """Execute a shell command and return stdout, stderr, and exit code."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out after 120 seconds."}
    except Exception as e:
        return {"error": str(e)}
