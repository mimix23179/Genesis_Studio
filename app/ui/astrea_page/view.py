from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import butterflyui as ui

from .dataset_captioner_page import DatasetCaptionerPage
from .generator_page import GeneratorPage
from .trainer_page import TrainerPage


class AstreaPage:
    """Astrea workspace split into module-backed pages for generation, training, and captioning."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        self._palette: dict[str, str] | None = None
        self._glass_mode = False
        self._mode = "generate"
        self._snapshot: dict[str, Any] = {}

        self._on_refresh: Callable[[], None] | None = None
        self._on_generate: Callable[[dict[str, Any]], None] | None = None
        self._on_train: Callable[[dict[str, Any]], None] | None = None
        self._on_caption: Callable[[dict[str, Any]], None] | None = None
        self._on_build_dataset: Callable[[dict[str, Any]], None] | None = None
        self._on_cancel: Callable[[], None] | None = None
        self._on_mode_change: Callable[[str], None] | None = None

        self.generator_page = GeneratorPage()
        self.trainer_page = TrainerPage(workspace_root)
        self.captioner_page = DatasetCaptionerPage(workspace_root)

        self.title = ui.Text("Astrea", class_name="type-display-sm")
        self.subtitle = ui.Text(
            "Genesis-native generation, training, and dataset preparation for sd-scripts with a full-stage module workspace.",
            class_name="type-body-md gs-muted",
        )
        self.status = ui.Text("Astrea idle", class_name="type-body-sm gs-muted")
        self.scripts_root = ui.Text(str(self.workspace_root / "genesis" / "astrea" / "sd-scripts"), class_name="type-caption gs-muted")
        self.capabilities = ui.Text("Capabilities unavailable", class_name="type-body-sm gs-muted")
        self.page_blurb = ui.Text("Generator page active.", class_name="type-body-sm gs-muted")

        self.refresh_button = ui.Button("Refresh", class_name="gs-button gs-outline gs-astrea-secondary")
        self.cancel_button = ui.Button("Cancel", class_name="gs-button gs-outline gs-astrea-secondary")
        self.page_tabs = ui.Tabs(
            labels=["Generator", "Trainer", "Captioner"],
            index=0,
            scrollable=False,
            events=["change"],
            class_name="gs-astrea-page-tabs",
            expand=True,
        )

        self.metric_images = ui.Text("0", class_name="type-heading-lg")
        self.metric_artifacts = ui.Text("0", class_name="type-heading-lg")
        self.metric_configs = ui.Text("0", class_name="type-heading-lg")
        self.metric_runs = ui.Text("0", class_name="type-heading-lg")

        self.recent_outputs = ui.ScrollableColumn(
            spacing=8,
            expand=True,
            content_padding={"left": 2, "right": 2, "top": 2, "bottom": 4},
        )
        self.config_list = ui.ScrollableColumn(
            spacing=8,
            expand=True,
            content_padding={"left": 2, "right": 2, "top": 2, "bottom": 4},
        )
        self.run_list = ui.ScrollableColumn(
            spacing=8,
            expand=True,
            content_padding={"left": 2, "right": 2, "top": 2, "bottom": 4},
        )
        self.logs = ui.MarkdownView(value="```text\nAstrea ready.\n```", selectable=True, scrollable=True)

        self._root_container: ui.Container | None = None
        self._preview_image: ui.Image | None = None
        self._preview_image_wrap: ui.Container | None = None
        self._preview_placeholder: ui.Text | None = None

    def bind_events(
        self,
        session: Any,
        *,
        on_refresh: Callable[[], None] | None = None,
        on_generate: Callable[[dict[str, Any]], None] | None = None,
        on_train: Callable[[dict[str, Any]], None] | None = None,
        on_caption: Callable[[dict[str, Any]], None] | None = None,
        on_build_dataset: Callable[[dict[str, Any]], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        on_mode_change: Callable[[str], None] | None = None,
    ) -> None:
        self._on_refresh = on_refresh
        self._on_generate = on_generate
        self._on_train = on_train
        self._on_caption = on_caption
        self._on_build_dataset = on_build_dataset
        self._on_cancel = on_cancel
        self._on_mode_change = on_mode_change

        self.refresh_button.on_click(session, self._handle_refresh)
        self.cancel_button.on_click(session, self._handle_cancel)
        self.page_tabs.on_change(session, self._handle_page_tab_change, inputs=self.page_tabs)

        self.generator_page.bind_events(session, on_generate=self._on_generate)
        self.trainer_page.bind_events(session, on_train=self._on_train, on_stop=self._on_cancel)
        self.captioner_page.bind_events(
            session,
            on_caption=self._on_caption,
            on_build_dataset=self._on_build_dataset,
            on_stop=self._on_cancel,
        )

    def build(self) -> ui.Container:
        if not self.page_tabs.children:
            self.page_tabs.set_children(
                [
                    self.generator_page.build(),
                    self.trainer_page.build(),
                    self.captioner_page.build(),
                ]
            )

        self._root_container = ui.Container(
            ui.Column(
                ui.Container(
                    self.page_tabs,
                    padding={"left": 12, "right": 12, "top": 0, "bottom": 12},
                    expand=True,
                ),
                spacing=0,
                expand=True,
            ),
            class_name="gs-page-root",
            expand=True,
        )
        self._set_mode(self._mode, emit=False)
        return self._root_container

    def set_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._snapshot = snapshot
        busy = bool(snapshot.get("busy"))
        job_kind = str(snapshot.get("job_kind") or "").strip()
        job_title = str(snapshot.get("job_title") or "").strip()
        self.status.patch(
            text=(f"Running {job_kind}: {job_title}" if busy and job_title else ("Astrea busy" if busy else "Astrea idle")),
            color="#64748B",
        )

        capabilities = snapshot.get("capabilities", {})
        script_items = capabilities.get("scripts", []) if isinstance(capabilities, dict) else []
        available = [item["name"] for item in script_items if isinstance(item, dict) and item.get("available")]
        self.capabilities.patch(text=("Available: " + ", ".join(available)) if available else "No sd-scripts capabilities detected")
        self.scripts_root.patch(text=str(snapshot.get("scripts_root", self.scripts_root.value)))

        generated = snapshot.get("generated_images", [])
        artifacts = snapshot.get("training_artifacts", [])
        configs = snapshot.get("dataset_configs", [])
        recent_runs = snapshot.get("recent_runs", [])
        self.metric_images.patch(text=str(len(generated)))
        self.metric_artifacts.patch(text=str(len(artifacts)))
        self.metric_configs.patch(text=str(len(configs)))
        self.metric_runs.patch(text=str(len(recent_runs)))

        latest_preview = str(snapshot.get("latest_preview", "")).strip()
        if self._preview_image is not None and self._preview_image_wrap is not None and self._preview_placeholder is not None:
            has_preview = bool(latest_preview and Path(latest_preview).exists())
            if has_preview:
                self._preview_image.patch(src=latest_preview)
            self._preview_image_wrap.patch(visible=has_preview)
            self._preview_placeholder.patch(
                text=("Latest image: " + Path(latest_preview).name) if has_preview else "Generate an image and Astrea will pin the latest preview here.",
                color="#64748B",
            )

        merged_outputs = [*generated[:6], *artifacts[:6]]
        self._replace_column(
            self.recent_outputs,
            [self._file_card(path, kind="image" if index < len(generated[:6]) else "artifact") for index, path in enumerate(merged_outputs)],
            empty_label="No images or artifacts yet.",
        )
        self._replace_column(
            self.config_list,
            [self._config_card(path) for path in configs[:10]],
            empty_label="No dataset configs yet.",
        )
        self._replace_column(
            self.run_list,
            [self._run_card(item) for item in recent_runs[:10] if isinstance(item, dict)],
            empty_label="No runs recorded yet.",
        )

        logs_value = str(snapshot.get("logs", "")).rstrip() or "Astrea ready."
        self.logs.patch(value=f"```text\n{logs_value}\n```")
        self.cancel_button.patch(disabled=not busy)

        self.generator_page.apply_capabilities(capabilities)
        self.trainer_page.apply_capabilities(capabilities)
        self.generator_page.set_snapshot(snapshot)
        self.trainer_page.set_snapshot(snapshot)
        self.captioner_page.set_snapshot(snapshot)

    def set_palette(self, palette: dict[str, str]) -> None:
        self._palette = palette
        self.generator_page.set_palette(palette)
        self.trainer_page.set_palette(palette)
        self.captioner_page.set_palette(palette)

    def set_glass_mode(self, enabled: bool) -> None:
        self._glass_mode = bool(enabled)
        self.generator_page.set_glass_mode(enabled)
        self.trainer_page.set_glass_mode(enabled)
        self.captioner_page.set_glass_mode(enabled)

    def _set_mode(self, mode: str, *, emit: bool) -> None:
        self._mode = mode if mode in {"generate", "train", "dataset"} else "generate"
        self.page_tabs.patch(index=self._mode_to_index(self._mode))

        page_blurbs = {
            "generate": "Generator page active.",
            "train": "Trainer page active.",
            "dataset": "Captioner page active.",
        }
        self.page_blurb.patch(text=page_blurbs.get(self._mode, "Generator page active."))
        if emit and callable(self._on_mode_change):
            self._on_mode_change(self._mode)

    def _handle_page_tab_change(self, index: int) -> None:
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

    def _metric_card(self, title: str, value: ui.Text, note: str) -> ui.Control:
        return ui.Surface(
            ui.Column(
                ui.Text(title, class_name="type-caption gs-muted"),
                value,
                ui.Text(note, class_name="type-caption gs-muted"),
                spacing=3,
            ),
            padding=14,
            class_name="gs-card gs-astrea-metric",
            radius=16,
            width=160,
        )

    def _file_card(self, path: str, *, kind: str) -> ui.Control:
        icon = "image" if kind == "image" else "description"
        accent = "type-caption gs-accent" if kind == "image" else "type-caption gs-muted"
        return ui.Surface(
            ui.Row(
                ui.Glyph(icon, size=18),
                ui.Expanded(
                    ui.Column(
                        ui.Text(Path(path).name, class_name="type-body-sm"),
                        ui.Text(str(Path(path).parent), class_name="type-caption gs-muted"),
                        spacing=2,
                    )
                ),
                ui.Text(kind.upper(), class_name=accent),
                spacing=10,
                cross_axis="center",
            ),
            padding=12,
            class_name="gs-card gs-astrea-output-item",
            radius=14,
        )

    def _config_card(self, path: str) -> ui.Control:
        return ui.Surface(
            ui.Column(
                ui.Text(Path(path).name, class_name="type-body-sm"),
                ui.Text(str(path), class_name="type-caption gs-muted"),
                spacing=3,
            ),
            padding=12,
            class_name="gs-card gs-astrea-config-item",
            radius=14,
        )

    def _run_card(self, item: dict[str, Any]) -> ui.Control:
        status = str(item.get("status", "unknown")).strip()
        tone = "gs-accent" if status == "completed" else ("gs-muted" if "failed" not in status.lower() else "")
        return ui.Surface(
            ui.Column(
                ui.Text(str(item.get("title", "Run")), class_name="type-body-sm"),
                ui.Text(str(item.get("output_path", "")), class_name="type-caption gs-muted"),
                ui.Text(status, class_name=("type-caption " + tone).strip()),
                spacing=3,
            ),
            padding=12,
            class_name="gs-card gs-astrea-stage",
            radius=14,
        )

    def _replace_column(self, column: ui.ScrollableColumn, controls: list[ui.Control], *, empty_label: str) -> None:
        column.controls = controls or [ui.Text(empty_label, class_name="type-body-sm gs-muted")]

    def _handle_refresh(self, _event: Any = None) -> None:
        if callable(self._on_refresh):
            self._on_refresh()

    def _handle_cancel(self, _event: Any = None) -> None:
        if callable(self._on_cancel):
            self._on_cancel()
