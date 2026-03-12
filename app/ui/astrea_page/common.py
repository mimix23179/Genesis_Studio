from __future__ import annotations

from typing import Any

import butterflyui as ui


def make_input(label: str, placeholder: str = "") -> ui.TextField:
    return ui.TextField(label=label, placeholder=placeholder, class_name="gs-input gs-astrea-input")


def make_text_area(label: str, placeholder: str = "", *, min_lines: int = 3, max_lines: int = 5) -> ui.TextArea:
    return ui.TextArea(
        label=label,
        placeholder=placeholder,
        class_name="gs-input gs-astrea-input",
        min_lines=min_lines,
        max_lines=max_lines,
    )


def make_select(label: str, value: str, options: list[dict[str, Any]] | None = None) -> ui.Select:
    selected = str(value or "").strip()
    fallback = {"label": selected or label, "value": selected or label.lower().replace(" ", "_")}
    return ui.Select(
        label=label,
        value=selected or fallback["value"],
        options=options or [fallback],
        class_name="gs-input gs-astrea-input",
    )


def make_switch(label: str, value: bool) -> ui.Switch:
    return ui.Switch(label=label, value=value, inline=True)


def expanded_row(*controls: ui.Control, spacing: int = 10) -> ui.Row:
    return ui.Row(*[ui.Expanded(control) for control in controls], spacing=spacing)


def stage_card(title: str, body: str, content: ui.Control, *, class_name: str = "gs-card gs-astrea-stage") -> ui.Control:
    return ui.Surface(
        ui.Column(
            ui.Text(title, class_name="type-heading-md"),
            ui.Text(body, class_name="type-body-sm gs-muted"),
            ui.Container(content, padding={"top": 10}),
            spacing=0,
        ),
        padding=16,
        class_name=class_name,
        radius=16,
    )


def read_value(control: Any) -> str:
    return str(getattr(control, "value", "") or "").strip()


def read_bool(control: Any) -> bool:
    return bool(getattr(control, "value", False))


def split_lines(value: str) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def set_select_options(select: ui.Select, values: list[str], *, fallback: str) -> None:
    normalized = [str(value).strip() for value in values if str(value).strip()]
    options = [{"label": value.upper() if value == "sdxl" else value.replace("_", " ").title(), "value": value} for value in normalized]
    current = str(getattr(select, "value", "") or "").strip()
    if not any(str(item.get("value", "")).strip() == current for item in options):
        current = fallback if fallback in normalized else (normalized[0] if normalized else "")
    select.patch(options=options or [{"label": fallback, "value": fallback}], value=current or fallback)
