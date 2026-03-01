"""File system tools for Genesis.

Deterministic, durable, provider-independent.
These work whether a model is loaded or not.
"""

from __future__ import annotations

import os
from pathlib import Path


async def fs_read(args: dict) -> dict:
    """Read a file and return its text content."""
    path = args["path"]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return {"text": f.read()}
    except FileNotFoundError:
        return {"error": f"File not found: {path}"}
    except Exception as exc:
        return {"error": str(exc)}


async def fs_write(args: dict) -> dict:
    """Write text to a file, creating directories as needed."""
    path = args["path"]
    text = args.get("text", "")
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return {"ok": True, "path": path, "bytes": len(text.encode("utf-8"))}
    except Exception as exc:
        return {"error": str(exc)}


async def fs_list(args: dict) -> dict:
    """List files and directories in a given path."""
    root = args.get("root", ".")
    try:
        items = []
        for name in sorted(os.listdir(root)):
            p = os.path.join(root, name)
            items.append({
                "name": name,
                "is_dir": os.path.isdir(p),
                "size": os.path.getsize(p) if os.path.isfile(p) else None,
            })
        return {"items": items}
    except FileNotFoundError:
        return {"error": f"Directory not found: {root}"}
    except Exception as exc:
        return {"error": str(exc)}


async def fs_mkdir(args: dict) -> dict:
    """Create a directory (and parents)."""
    path = args["path"]
    try:
        os.makedirs(path, exist_ok=True)
        return {"ok": True, "path": path}
    except Exception as exc:
        return {"error": str(exc)}


async def fs_delete(args: dict) -> dict:
    """Delete a file."""
    path = args["path"]
    try:
        os.remove(path)
        return {"ok": True, "path": path}
    except FileNotFoundError:
        return {"error": f"File not found: {path}"}
    except Exception as exc:
        return {"error": str(exc)}
