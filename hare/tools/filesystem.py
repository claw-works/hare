from pathlib import Path
from typing import Any


def read_file(path: str) -> dict[str, Any]:
    """Read file contents."""
    try:
        content = Path(path).expanduser().read_text(encoding="utf-8")
        return {"content": content}
    except Exception as e:
        return {"error": str(e)}


def write_file(path: str, content: str) -> dict[str, Any]:
    """Write content to a file, creating parent directories as needed."""
    try:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"success": True, "path": str(p)}
    except Exception as e:
        return {"error": str(e)}
