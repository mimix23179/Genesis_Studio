from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import butterflyui as ui


class AstreaSidebar:
    def __init__(self) -> None:
        self._palette: dict[str, str] | None = None
        self._glass_mode = False
        self._mode = "generate"
        self._state: dict[str, Any] = {}

        self._status = ui.Text("Astrea idle")
        self._summary = ui.Text("No outputs yet.")
        self._counts = ui.Text("0 images / 0 artifacts / 0 configs", font_size=11)
        self._capabilities = ui.Text("Capabilities unavailable", font_size=11)
        self._recent = ui.ScrollableColumn(spacing=8, expand=True)
        self._refresh_button = ui.Button("Refresh", class_name="gs-button gs-outline gs-astrea-secondary")
        self._cancel_button = ui.Button("Cancel", class_name="gs-button gs-outline gs-astrea-secondary")
        self._mode_tabs = ui.Tabs(
            labels=["Generator", "Trainer", "Captioner"],
            index=0,
            scrollable=True,
            events=["change"],
            class_name="gs-astrea-sidebar-tabs",
        )
        self.on_refresh: Callable[[], None] | None = None
        self.on_cancel: Callable[[], None] | None = None
        self.on_switch_mode: Callable[[str], None] | None = None

    def bind_events(
        self,
        session: Any,
        *,
        on_refresh: Callable[[], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        on_switch_mode: Callable[[str], None] | None = None,
    ) -> None:
        self.on_refresh = on_refresh
        self.on_cancel = on_cancel
        self.on_switch_mode = on_switch_mode
        self._refresh_button.on_click(session, lambda _e: self.on_refresh and self.on_refresh())
        self._cancel_button.on_click(session, lambda _e: self.on_cancel and self.on_cancel())
        self._mode_tabs.on_change(session, self._handle_tab_change, inputs=self._mode_tabs)

    def build(self) -> ui.Control:
        if not self._mode_tabs.children:
            self._mode_tabs.set_children(
                [
                    ui.Container(height=1),
                    ui.Container(height=1),
                    ui.Container(height=1),
                ]
            )

        self._root = ui.Column(
            spacing=16,
            controls=[
                ui.Text("Astrea", class_name="type-heading-md"),
                ui.Text("Generation, training, and caption prep inside Genesis Studio."),
                ui.Surface(
                    class_name="gs-card gs-astrea-sidebar-card",
                    content=ui.Column(spacing=8, controls=[self._status, self._summary, self._counts, self._capabilities]),
                ),
                self._mode_tabs,
                ui.Row(spacing=10, controls=[self._refresh_button, self._cancel_button]),
                ui.Text("Recent outputs", class_name="type-heading-sm"),
                ui.Container(content=self._recent, expand=True),
            ],
        )
        self._set_mode(self._mode, emit=False)
        return self._root

    def set_state(self, state: dict[str, Any]) -> None:
        self._state = state
        busy = bool(state.get("busy"))
        self._status.value = f"Running {state.get('job_kind') or 'job'}" if busy else "Astrea idle"

        total_images = len(state.get("generated_images", []))
        total_artifacts = len(state.get("training_artifacts", []))
        total_configs = len(state.get("dataset_configs", []))
        self._summary.value = f"{total_images} images, {total_artifacts} training artifacts."
        self._counts.value = f"{total_images} images / {total_artifacts} artifacts / {total_configs} configs"

        capabilities = state.get("capabilities", {})
        available = [
            str(item.get("name", "")).strip()
            for item in capabilities.get("scripts", [])
            if isinstance(item, dict) and item.get("available")
        ] if isinstance(capabilities, dict) else []
        self._capabilities.value = ("Scripts: " + ", ".join(available)) if available else "Scripts unavailable"

        self._recent.controls = []
        for path in state.get("generated_images", [])[:4]:
            self._recent.controls.append(
                ui.Surface(
                    class_name="gs-card gs-astrea-output-item",
                    content=ui.Row(
                        spacing=10,
                        controls=[
                            ui.Image(src=path, width=52, height=52, fit="cover", radius=12),
                            ui.Expanded(content=ui.Text(Path(path).name)),
                        ],
                    ),
                )
            )
        for artifact in state.get("training_artifacts", [])[:4]:
            self._recent.controls.append(
                ui.Surface(class_name="gs-card gs-astrea-output-item", content=ui.Text(Path(artifact).name))
            )
        for config in state.get("dataset_configs", [])[:4]:
            self._recent.controls.append(
                ui.Surface(class_name="gs-card gs-astrea-output-item", content=ui.Text(Path(config).name))
            )
        self._cancel_button.disabled = not busy

    def set_palette(self, palette: dict[str, str]) -> None:
        self._palette = palette

    def set_glass_mode(self, enabled: bool) -> None:
        self._glass_mode = enabled

    def _set_mode(self, mode: str, *, emit: bool) -> None:
        self._mode = mode if mode in {"generate", "train", "dataset"} else "generate"
        self._mode_tabs.patch(index=self._mode_to_index(self._mode))
        if emit and self.on_switch_mode is not None:
            self.on_switch_mode(self._mode)

    def _handle_tab_change(self, index: int) -> None:
        self._set_mode(self._index_to_mode(index), emit=True)

    def _mode_to_index(self, mode: str) -> int:
        return {
            "generate": 0,
            "train": 1,
            "dataset": 2,
        }.get(mode, 0)

    def _index_to_mode(self, index: int) -> str:
        return {
            0: "generate",
            1: "train",
            2: "dataset",
        }.get(int(index), "generate")
