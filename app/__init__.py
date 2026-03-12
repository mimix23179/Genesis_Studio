from __future__ import annotations

import socket
import sys
from pathlib import Path


def _bootstrap_local_butterflyui() -> None:
    root = Path(__file__).resolve().parents[2]
    source = root / "ButterflyUI" / "butterflyui" / "sdk" / "python" / "packages" / "butterflyui" / "src"
    if not source.exists():
        return
    source_str = str(source)
    if source_str not in sys.path:
        sys.path.insert(0, source_str)


_bootstrap_local_butterflyui()

import butterflyui as butterfly

from app.config import resolve_paths
from app.ui.shell import GenesisStudioShell


def _bootstrap(page: butterfly.Page) -> None:
    shell = GenesisStudioShell(page=page, paths=resolve_paths())
    shell.mount()


def _pick_ui_port(start: int = 8765, span: int = 20) -> int:
    for port in range(start, start + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free local port found for ButterflyUI runtime")


def main() -> int:
    return butterfly.run_desktop(_bootstrap, host="127.0.0.1", port=_pick_ui_port())


__all__ = ["main"]
