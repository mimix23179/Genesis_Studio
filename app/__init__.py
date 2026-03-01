from __future__ import annotations

import butterflyui as butterfly
import socket

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
