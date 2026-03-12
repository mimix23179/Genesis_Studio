from __future__ import annotations

from typing import Any, Callable

import butterflyui as ui


class ModelsPage:
    """Paged Ollama library browser with detail view and pull controls."""

    _BG = "#F6F8FC"
    _SURFACE = "#FFFFFF"
    _SURFACE_ALT = "#F8FAFC"
    _BORDER = "#D6DEE8"
    _TEXT = "#0F172A"
    _MUTED = "#64748B"
    _ACCENT = "#10A37F"
    _ON_ACCENT = "#FFFFFF"
    _SUCCESS = "#047857"
    _ERROR = "#B91C1C"

    def __init__(self) -> None:
        self._bound_session: Any = None
        self._on_refresh: Callable[[], None] | None = None
        self._on_page_change: Callable[[int], None] | None = None
        self._on_open_model: Callable[[str], None] | None = None
        self._on_back: Callable[[], None] | None = None
        self._on_pull: Callable[[], None] | None = None
        self._on_variant_change: Callable[[str], None] | None = None
        self._card_controls: dict[str, ui.ArtifactCard] = {}
        self._glass_mode = False
        self._detail_name = ""

        self.title = ui.Text("Ollama Models", font_size=22, font_weight="700", color=self._TEXT)
        self.subtitle = ui.Text(
            "Browse the Ollama library, inspect details, and pull models without using the terminal.",
            font_size=12,
            color=self._MUTED,
        )
        self.status = ui.Text("Library idle", font_size=12, color=self._MUTED)
        self.summary = ui.Text("No models loaded", font_size=12, color=self._MUTED)

        self.refresh_button = ui.Button(
            text="Refresh",
            class_name="gs-button gs-outline",
            variant="outlined",
            events=["click"],
            radius=10,
        )

        self.catalog_list = ui.ScrollableColumn(
            spacing=12,
            expand=True,
            content_padding={"left": 4, "right": 4, "top": 4, "bottom": 12},
        )
        self.pagination = ui.Pagination(
            page=1,
            page_count=1,
            max_visible=7,
            show_edges=True,
            events=["change"],
        )

        self.back_button = ui.Button(
            text="Back",
            class_name="gs-button gs-outline",
            variant="outlined",
            events=["click"],
            radius=10,
        )
        self.pull_button = ui.Button(
            text="Pull",
            class_name="gs-button gs-primary",
            variant="filled",
            events=["click"],
            radius=10,
            font_weight="700",
        )
        self.detail_title = ui.Text("Select a model", font_size=22, font_weight="700", color=self._TEXT)
        self.detail_description = ui.Text("", font_size=13, color=self._MUTED)
        self.detail_rating = ui.Text("Rating: N/A", font_size=12, color=self._MUTED)
        self.detail_stats = ui.Text("", font_size=12, color=self._MUTED)
        self.detail_status = ui.Text("Model detail idle", font_size=12, color=self._MUTED)
        self.detail_variant_select = ui.Select(
            label="Variant",
            class_name="gs-input",
            value="",
            options=[{"label": "Default", "value": ""}],
            events=["change"],
            width=340,
        )
        self.detail_readme = ui.MarkdownView(value="", selectable=True, scrollable=True)

        self.catalog_view = ui.Container(expand=True)
        self.detail_view = ui.Container(expand=True, visible=False)
        self._root_container: ui.Container | None = None
        self._header_surface: ui.Surface | None = None
        self._catalog_surface: ui.Surface | None = None
        self._detail_header_surface: ui.Surface | None = None
        self._detail_readme_surface: ui.Surface | None = None

    def bind_events(
        self,
        session,
        *,
        on_refresh: Callable[[], None],
        on_page_change: Callable[[int], None],
        on_open_model: Callable[[str], None],
        on_back: Callable[[], None],
        on_pull: Callable[[], None],
        on_variant_change: Callable[[str], None],
    ) -> None:
        self._bound_session = session
        self._on_refresh = on_refresh
        self._on_page_change = on_page_change
        self._on_open_model = on_open_model
        self._on_back = on_back
        self._on_pull = on_pull
        self._on_variant_change = on_variant_change

        self.refresh_button.on_click(session, self._handle_refresh)
        self.pagination.on_change(session, self._handle_page_change)
        self.back_button.on_click(session, self._handle_back)
        self.pull_button.on_click(session, self._handle_pull)
        self.detail_variant_select.on_change(session, self._handle_variant_change, inputs=[self.detail_variant_select])
        self._bind_card_events()

    def build(self) -> ui.Container:
        self._header_surface = ui.Surface(
            ui.Row(
                ui.Column(self.title, self.subtitle, self.status, spacing=4),
                ui.Spacer(),
                self.refresh_button,
                spacing=12,
                cross_axis="start",
            ),
            padding=16,
            class_name="gs-page-header",
            radius=14,
        )

        catalog_body = ui.Column(
            ui.Container(self.summary, padding={"left": 4, "right": 4, "top": 4, "bottom": 8}),
            ui.Expanded(self.catalog_list),
            ui.Container(self.pagination, padding={"left": 4, "right": 4, "top": 8, "bottom": 4}),
            spacing=0,
            expand=True,
        )
        self._catalog_surface = ui.Surface(
            catalog_body,
            padding=14,
            class_name="gs-card",
            radius=14,
        )
        self.catalog_view = ui.Container(
            self._catalog_surface,
            expand=True,
            visible=True,
        )

        self._detail_header_surface = ui.Surface(
            ui.Column(
                ui.Row(self.back_button, ui.Spacer(), self.pull_button, spacing=10),
                ui.Column(self.detail_title, self.detail_description, spacing=4),
                ui.Row(self.detail_rating, ui.Spacer(), self.detail_stats, spacing=10),
                ui.Row(self.detail_variant_select, ui.Spacer(), self.detail_status, spacing=12, cross_axis="center"),
                spacing=10,
            ),
            padding=16,
            class_name="gs-card",
            radius=14,
        )
        self._detail_readme_surface = ui.Surface(
            ui.Container(self.detail_readme, expand=True),
            padding=16,
            class_name="gs-card",
            radius=14,
        )
        self.detail_view = ui.Container(
            ui.Column(
                self._detail_header_surface,
                ui.Expanded(
                    child=self._detail_readme_surface
                ),
                spacing=10,
                expand=True,
            ),
            expand=True,
            visible=False,
        )

        stack = ui.Stack(self.catalog_view, self.detail_view, fit="expand", expand=True)
        self._root_container = ui.Container(
            ui.Column(ui.Container(self._header_surface, padding={"left": 12, "right": 12, "top": 12, "bottom": 6}), ui.Expanded(stack), spacing=0, expand=True),
            expand=True,
            class_name="gs-page-root",
        )
        return self._root_container

    def set_status(self, text: str, *, error: bool = False, success: bool = False) -> None:
        color = self._MUTED
        if error:
            color = self._ERROR
        elif success:
            color = self._SUCCESS
        self.status.patch(text=text.strip() or "Library idle", color=color)

    def render_catalog(
        self,
        items: list[dict[str, Any]],
        *,
        page: int,
        page_count: int,
        total_count: int,
        installed_models: set[str],
        active_model: str,
    ) -> None:
        self.show_catalog()
        self.catalog_list.children.clear()
        self._card_controls.clear()

        if not items:
            self.catalog_list.children.append(
                ui.Surface(
                    ui.Column(
                        ui.Text("No models found", font_size=16, font_weight="700", color=self._TEXT),
                        ui.Text("Refresh the Ollama library to try again.", font_size=12, color=self._MUTED),
                        spacing=6,
                    ),
                    padding=18,
                    class_name="gs-card",
                    radius=14,
                )
            )
        else:
            for item in items:
                name = str(item.get("name", "")).strip()
                if not name:
                    continue
                installed = any(str(target).strip() in installed_models for target in self._candidate_targets(item))
                is_active = bool(active_model and active_model in self._candidate_targets(item))
                badge = "Active" if is_active else ("Installed" if installed else "Library")
                message = str(item.get("description", "")).strip()
                meta_parts = []
                capabilities = item.get("capabilities", [])
                variants = item.get("variants", [])
                pulls = str(item.get("pulls", "")).strip()
                updated = str(item.get("updated", "")).strip()
                if capabilities:
                    meta_parts.append("Capabilities: " + ", ".join(str(part) for part in capabilities[:4]))
                if variants:
                    meta_parts.append("Variants: " + ", ".join(str(part) for part in variants[:6]))
                stats = " | ".join(part for part in [f"Pulls {pulls}" if pulls else "", f"Updated {updated}" if updated else ""] if part)
                if stats:
                    meta_parts.append(stats)
                details = ui.Column(*[ui.Text(part, font_size=11, color=self._MUTED) for part in meta_parts], spacing=4)
                card = ui.ArtifactCard(
                    details,
                    title=name,
                    class_name="gs-artifact gs-artifact-active" if is_active else "gs-artifact",
                    label=badge,
                    message=message,
                    action_label="Open",
                    clickable=True,
                    events=["click", "action"],
                )
                self._card_controls[name] = card
                self.catalog_list.children.append(card)

        self.summary.patch(text=f"Showing page {page} of {page_count} | {total_count} models total")
        self.pagination.patch(page=page, page_count=max(1, page_count), total_items=max(0, total_count))
        self._bind_card_events()

    def show_detail(
        self,
        detail: dict[str, Any],
        *,
        selected_target: str,
        installed_models: set[str],
        active_model: str,
        pull_in_progress: bool,
    ) -> None:
        self._detail_name = str(detail.get("name", "")).strip()
        self.catalog_view.patch(visible=False)
        self.detail_view.patch(visible=True)

        description = str(detail.get("description", "")).strip()
        pulls = str(detail.get("pulls", "")).strip()
        tags = str(detail.get("tags", "")).strip()
        updated = str(detail.get("updated", "")).strip()
        rating_text = str(detail.get("rating_text", "N/A")).strip() or "N/A"
        rating_note = str(detail.get("rating_note", "")).strip()
        popularity = detail.get("popularity_score")
        targets = [str(item).strip() for item in detail.get("pull_targets", []) if str(item).strip()]
        if not targets:
            targets = [self._detail_name]
        selected = selected_target if selected_target in targets else targets[0]
        installed = selected in installed_models
        active = bool(active_model and active_model == selected)

        self.detail_title.patch(text=self._detail_name or "Model Detail")
        self.detail_description.patch(text=description or "No description available.")
        popularity_text = f" | Popularity {popularity}/5" if popularity is not None else ""
        self.detail_rating.patch(text=f"Rating: {rating_text}{popularity_text}" + (f" | {rating_note}" if rating_note else ""))
        stats = " | ".join(part for part in [f"Pulls {pulls}" if pulls else "", f"Tags {tags}" if tags else "", f"Updated {updated}" if updated else ""] if part)
        self.detail_stats.patch(text=stats or "No library stats available")
        self.detail_variant_select.patch(options=[{"label": target, "value": target} for target in targets], value=selected)
        pull_label = "Pulling..." if pull_in_progress else ("Pulled" if installed else "Pull")
        self.pull_button.patch(text=pull_label, disabled=pull_in_progress or installed)
        status_parts = []
        if active:
            status_parts.append("Active runtime model")
        if installed:
            status_parts.append("Installed locally")
        if pull_in_progress:
            status_parts.append("Download in progress")
        self.detail_status.patch(text=" | ".join(status_parts) or "Ready")
        self.detail_readme.patch(value=str(detail.get("readme_markdown", "")).strip() or "No README available.")

    def show_catalog(self) -> None:
        self.catalog_view.patch(visible=True)
        self.detail_view.patch(visible=False)

    def set_glass_mode(self, enabled: bool) -> None:
        self._glass_mode = bool(enabled)

    def set_palette(self, palette: dict[str, str]) -> None:
        self._BG = palette.get("bg", self._BG)
        self._SURFACE = palette.get("surface", self._SURFACE)
        self._SURFACE_ALT = palette.get("surface_alt", self._SURFACE_ALT)
        self._BORDER = palette.get("border", self._BORDER)
        self._TEXT = palette.get("text", self._TEXT)
        self._MUTED = palette.get("muted", self._MUTED)
        self._ACCENT = palette.get("accent", self._ACCENT)
        self._ON_ACCENT = palette.get("on_accent", self._ON_ACCENT)

        try:
            self.title.patch(color=self._TEXT)
            self.subtitle.patch(color=self._MUTED)
            self.summary.patch(color=self._MUTED)
            self.detail_title.patch(color=self._TEXT)
            self.detail_description.patch(color=self._MUTED)
            self.detail_rating.patch(color=self._MUTED)
            self.detail_stats.patch(color=self._MUTED)
            self.detail_status.patch(color=self._MUTED)
        except Exception:
            pass

    def set_accent(self, color: str) -> None:
        self._ACCENT = str(color or "").strip() or self._ACCENT

    def _bind_card_events(self) -> None:
        if self._bound_session is None:
            return
        for name, card in self._card_controls.items():
            card.on_tap(self._bound_session, lambda _event=None, target=name: self._emit_open(target))
            card.on_event(self._bound_session, "action", lambda _event=None, target=name: self._emit_open(target))

    def _emit_open(self, model_name: str) -> None:
        if callable(self._on_open_model):
            self._on_open_model(model_name)

    def _handle_refresh(self, _event=None) -> None:
        if callable(self._on_refresh):
            self._on_refresh()

    def _handle_page_change(self, value=None, event=None) -> None:
        selected = self._extract_page(value=value, event=event)
        if callable(self._on_page_change):
            self._on_page_change(selected)

    def _handle_back(self, _event=None) -> None:
        if callable(self._on_back):
            self._on_back()

    def _handle_pull(self, _event=None) -> None:
        if callable(self._on_pull):
            self._on_pull()

    def _handle_variant_change(self, value=None, event=None) -> None:
        selected = str(value or "").strip()
        if not selected and isinstance(event, dict):
            payload = event.get("payload")
            if isinstance(payload, dict):
                selected = str(payload.get("value", "")).strip()
        if not selected:
            try:
                selected = str(self.detail_variant_select.to_dict().get("props", {}).get("value", "")).strip()
            except Exception:
                selected = ""
        if callable(self._on_variant_change):
            self._on_variant_change(selected)

    @staticmethod
    def _candidate_targets(item: dict[str, Any]) -> list[str]:
        name = str(item.get("name", "")).strip()
        variants = [str(variant).strip() for variant in item.get("variants", []) if str(variant).strip()]
        if not variants:
            return [name] if name else []
        return [f"{name}:{variant}" for variant in variants]

    @staticmethod
    def _extract_page(*, value=None, event=None) -> int:
        if isinstance(value, int):
            return max(1, value)
        if isinstance(value, str) and value.strip().isdigit():
            return max(1, int(value.strip()))
        if isinstance(event, dict):
            payload = event.get("payload")
            if isinstance(payload, dict):
                page = payload.get("page", payload.get("value"))
                if isinstance(page, int):
                    return max(1, page)
                if isinstance(page, str) and page.strip().isdigit():
                    return max(1, int(page.strip()))
        return 1
