from __future__ import annotations

import butterflyui as ui

from app.config import resolve_paths
from app.ui import GenesisStudioShell


def _bootstrap(page: ui.Page) -> None:
    shell = GenesisStudioShell(page=page, paths=resolve_paths())
    shell.mount()


def main() -> int:
    return ui.run_desktop(_bootstrap)
