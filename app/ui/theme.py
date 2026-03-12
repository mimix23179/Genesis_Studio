from __future__ import annotations

import json
from typing import Iterable


def _normalize_hex(value: str, fallback: str) -> str:
    raw = str(value or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return fallback
    try:
        int(raw, 16)
    except ValueError:
        return fallback
    return f"#{raw.upper()}"


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    normalized = _normalize_hex(value, "#10A37F").lstrip("#")
    return tuple(int(normalized[index:index + 2], 16) for index in (0, 2, 4))


def _rgb_to_hex(values: Iterable[int]) -> str:
    red, green, blue = (max(0, min(255, int(channel))) for channel in values)
    return f"#{red:02X}{green:02X}{blue:02X}"


def mix(color_a: str, color_b: str, weight_a: float) -> str:
    weight = max(0.0, min(1.0, float(weight_a)))
    red_a, green_a, blue_a = _hex_to_rgb(color_a)
    red_b, green_b, blue_b = _hex_to_rgb(color_b)
    return _rgb_to_hex(
        (
            round(red_a * weight + red_b * (1.0 - weight)),
            round(green_a * weight + green_b * (1.0 - weight)),
            round(blue_a * weight + blue_b * (1.0 - weight)),
        )
    )


def with_alpha(color: str, alpha: float) -> str:
    normalized = _normalize_hex(color, "#10A37F").lstrip("#")
    channel = max(0, min(255, round(float(alpha) * 255)))
    return f"#{channel:02X}{normalized}"


def text_on(color: str) -> str:
    red, green, blue = _hex_to_rgb(color)
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255.0
    return "#0F172A" if luminance > 0.66 else "#FFFFFF"


def _shadow(
    color: str,
    *,
    blur: float,
    spread: float = 0.0,
    offset_x: float = 0.0,
    offset_y: float = 12.0,
) -> str:
    return json.dumps(
        [
            {
                "color": color,
                "blur": blur,
                "spread": spread,
                "offset": [offset_x, offset_y],
            }
        ]
    )


def _gradient(colors: list[str], *, begin: str = "top_left", end: str = "bottom_right") -> str:
    return json.dumps({"colors": colors, "begin": begin, "end": end})


def build_palette(accent: str, *, dark: bool = True) -> dict[str, str]:
    accent_color = _normalize_hex(accent, "#10A37F")
    on_accent = text_on(accent_color)

    if dark:
        return {
            "accent": accent_color,
            "on_accent": on_accent,
            "bg": mix(accent_color, "#050814", 0.08),
            "surface": with_alpha(mix(accent_color, "#0B1220", 0.16), 0.92),
            "surface_alt": with_alpha(mix(accent_color, "#10192D", 0.20), 0.95),
            "thread_bg": with_alpha(mix(accent_color, "#0C1424", 0.20), 0.88),
            "input_bg": with_alpha(mix(accent_color, "#0D1628", 0.24), 0.96),
            "border": with_alpha(mix(accent_color, "#CBD5E1", 0.16), 0.32),
            "text": mix(accent_color, "#F8FAFC", 0.05),
            "muted": mix(accent_color, "#94A3B8", 0.12),
            "user_bg": with_alpha(mix(accent_color, "#16213A", 0.34), 0.92),
            "assist_bg": with_alpha(mix(accent_color, "#0C162A", 0.16), 0.90),
            "active_bg": with_alpha(mix(accent_color, "#19284A", 0.42), 0.96),
            "active_border": with_alpha(mix(accent_color, "#FFFFFF", 0.30), 0.52),
            "active_text": mix(accent_color, "#FFFFFF", 0.14),
            "toolbar_gradient_start": with_alpha(mix(accent_color, "#162541", 0.28), 0.96),
            "toolbar_gradient_end": with_alpha(mix(accent_color, "#0C1425", 0.12), 0.90),
            "overlay_scrim": with_alpha("#020617", 0.68),
            "glow": with_alpha(accent_color, 0.34),
            "glass_bg": with_alpha(mix(accent_color, "#08101E", 0.22), 0.86),
            "glass_surface": with_alpha(mix(accent_color, "#0E172B", 0.26), 0.78),
            "glass_surface_alt": with_alpha(mix(accent_color, "#131E35", 0.24), 0.74),
            "glass_thread_bg": with_alpha(mix(accent_color, "#101A30", 0.26), 0.72),
            "glass_input_bg": with_alpha(mix(accent_color, "#0D1628", 0.30), 0.82),
            "glass_border": with_alpha(mix(accent_color, "#CBD5E1", 0.18), 0.34),
            "success": "#34D399",
            "error": "#F87171",
            "galaxy_primary": mix(accent_color, "#7C3AED", 0.22),
            "galaxy_secondary": mix(accent_color, "#38BDF8", 0.16),
            "galaxy_hot": mix(accent_color, "#FB7185", 0.16),
            "galaxy_gold": mix(accent_color, "#F59E0B", 0.12),
            "galaxy_dust": with_alpha("#E2E8F0", 0.08),
            "hero_scrim": with_alpha(mix(accent_color, "#020617", 0.08), 0.20),
        }

    return {
        "accent": accent_color,
        "on_accent": on_accent,
        "bg": mix(accent_color, "#F4F6FB", 0.09),
        "surface": mix(accent_color, "#FFFFFF", 0.11),
        "surface_alt": mix(accent_color, "#F8FAFC", 0.18),
        "thread_bg": mix(accent_color, "#FFFFFF", 0.07),
        "input_bg": mix(accent_color, "#FFFFFF", 0.10),
        "border": mix(accent_color, "#CBD5E1", 0.26),
        "text": mix(accent_color, "#0F172A", 0.07),
        "muted": mix(accent_color, "#64748B", 0.14),
        "user_bg": mix(accent_color, "#FFFFFF", 0.20),
        "assist_bg": mix(accent_color, "#FFFFFF", 0.08),
        "active_bg": mix(accent_color, "#FFFFFF", 0.28),
        "active_border": mix(accent_color, "#CBD5E1", 0.38),
        "active_text": mix(accent_color, "#0F172A", 0.12),
        "toolbar_gradient_start": mix(accent_color, "#FFFFFF", 0.18),
        "toolbar_gradient_end": mix(accent_color, "#F8FAFC", 0.10),
        "overlay_scrim": with_alpha(mix(accent_color, "#0B1220", 0.18), 0.45),
        "glow": with_alpha(accent_color, 0.34),
        "glass_bg": with_alpha(mix(accent_color, "#EEF2FF", 0.20), 0.74),
        "glass_surface": with_alpha(mix(accent_color, "#FFFFFF", 0.18), 0.80),
        "glass_surface_alt": with_alpha(mix(accent_color, "#F8FAFC", 0.22), 0.78),
        "glass_thread_bg": with_alpha(mix(accent_color, "#FFFFFF", 0.14), 0.76),
        "glass_input_bg": with_alpha(mix(accent_color, "#FFFFFF", 0.16), 0.86),
        "glass_border": with_alpha(mix(accent_color, "#CBD5E1", 0.30), 0.64),
        "success": "#047857",
        "error": "#B91C1C",
        "galaxy_primary": mix(accent_color, "#7C3AED", 0.18),
        "galaxy_secondary": mix(accent_color, "#38BDF8", 0.14),
        "galaxy_hot": mix(accent_color, "#FB7185", 0.14),
        "galaxy_gold": mix(accent_color, "#F59E0B", 0.12),
        "galaxy_dust": with_alpha("#0F172A", 0.06),
        "hero_scrim": with_alpha("#FFFFFF", 0.12),
    }


def build_stylesheet(palette: dict[str, str], *, glass: bool = False) -> str:
    surface = palette.get("glass_surface", palette.get("surface", "#FFFFFF")) if glass else palette.get("surface", "#FFFFFF")
    surface_alt = palette.get("glass_surface_alt", palette.get("surface_alt", "#F8FAFC")) if glass else palette.get("surface_alt", "#F8FAFC")
    border = palette.get("glass_border", palette.get("border", "#CBD5E1")) if glass else palette.get("border", "#CBD5E1")
    input_bg = palette.get("glass_input_bg", palette.get("input_bg", "#FFFFFF")) if glass else palette.get("input_bg", "#FFFFFF")
    canvas = palette.get("glass_bg", palette.get("bg", "#F4F6FB")) if glass else palette.get("bg", "#F4F6FB")
    accent = palette.get("accent", "#10A37F")
    on_accent = palette.get("on_accent", text_on(accent))
    text = palette.get("text", "#0F172A")
    muted = palette.get("muted", "#64748B")
    error = palette.get("error", "#B91C1C")
    glow = palette.get("glow", "#2210A37F")
    overlay = palette.get("overlay_scrim", "#780B1220")
    hero_scrim = palette.get("hero_scrim", "#11000000")
    input_shadow = _shadow(with_alpha(accent, 0.18), blur=18, offset_y=6)
    base_shadow = _shadow(glow, blur=24, spread=1, offset_y=12)
    hover_shadow = _shadow(glow, blur=30, spread=2, offset_y=16)
    accent_shadow = _shadow(with_alpha(accent, 0.40), blur=34, spread=2, offset_y=16)
    panel_shadow = _shadow(with_alpha(mix(accent, "#0F172A", 0.26), 0.38), blur=38, spread=3, offset_y=18)
    drawer_shadow = _shadow(with_alpha(mix(accent, "#020617", 0.18), 0.46), blur=52, spread=6, offset_y=24)
    toolbar_gradient = _gradient(
        [
            palette.get("toolbar_gradient_start", surface),
            palette.get("toolbar_gradient_end", surface_alt),
        ]
    )

    return f"""
:root {{
    --gs-accent: {accent};
    --gs-surface: {surface};
    --gs-surface-alt: {surface_alt};
    --gs-border: {border};
    --gs-text: {text};
    --gs-muted: {muted};
}}

Button.gs-button {{
    radius: 14;
    border_width: 1;
    background_color: {surface};
    border_color: {border};
    text_color: {text};
    label_text_color: {text};
    shadow: {base_shadow};
}}

Button.gs-button:hover {{
    translate_y: -2;
    shadow: {hover_shadow};
}}

Button.gs-primary {{
    background_color: {accent};
    border_color: {with_alpha(mix(accent, "#FFFFFF", 0.18), 0.44)};
    text_color: {on_accent};
    label_text_color: {on_accent};
    shadow: {accent_shadow};
}}

Button.gs-primary:hover {{
    background_color: {mix(accent, "#FFFFFF", 0.18)};
}}

Button.gs-outline {{
    background_color: {surface_alt};
    border_color: {border};
    text_color: {text};
    label_text_color: {text};
}}

Button.gs-outline:hover {{
    background_color: {surface};
    border_color: {accent};
}}

Button.gs-pill {{
    radius: 999;
}}

GlyphButton.gs-rail {{
    background_color: {surface};
    border_color: {border};
    border_width: 1;
    radius: 14;
    shadow: {base_shadow};
}}

GlyphButton.gs-rail:hover {{
    translate_y: -1;
    background_color: {surface_alt};
    border_color: {accent};
}}

Surface.gs-toolbar {{
    background_color: {surface};
    border_color: {border};
    border_width: 1;
    radius: 18;
    gradient: {toolbar_gradient};
    shadow: {panel_shadow};
    backdrop_blur: {24 if glass else 10};
}}

Surface.gs-shell-rail {{
    background_color: {surface};
    border_color: {border};
    border_width: 1;
    backdrop_blur: {20 if glass else 8};
}}

Surface.gs-panel {{
    background_color: {surface};
    border_color: {border};
    border_width: 1;
    radius: 18;
    shadow: {panel_shadow};
    backdrop_blur: {22 if glass else 10};
}}

Surface.gs-card {{
    background_color: {surface_alt};
    border_color: {border};
    border_width: 1;
    radius: 18;
    shadow: {base_shadow};
    backdrop_blur: {18 if glass else 8};
}}

Surface.gs-page-header {{
    background_color: {surface};
    border_color: {border};
    border_width: 1;
    radius: 20;
    shadow: {panel_shadow};
    backdrop_blur: {22 if glass else 10};
}}

Surface.gs-drawer {{
    background_color: {surface_alt};
    border_color: {border};
    border_width: 1;
    radius: 24;
    shadow: {drawer_shadow};
    backdrop_blur: {26 if glass else 12};
}}

Surface.gs-accent-card {{
    border_width: 1;
    radius: 18;
    shadow: {drawer_shadow};
    backdrop_blur: {18 if glass else 8};
}}

ArtifactCard.gs-artifact {{
    background_color: {surface};
    border_color: {border};
    border_width: 1;
    radius: 18;
    shadow: {base_shadow};
}}

ArtifactCard.gs-artifact:hover {{
    translate_y: -2;
    border_color: {accent};
}}

TextField.gs-input,
TextArea.gs-editor,
Select.gs-input {{
    background_color: {input_bg};
    border_color: {border};
    border_width: 1;
    radius: 12;
    text_color: {text};
    label_text_color: {muted};
    helper_text_color: {muted};
    placeholder_text_color: {with_alpha(text, 0.54)};
    shadow: {input_shadow};
}}

Outline.gs-outline {{
    background_color: {surface};
    border_color: {border};
    border_width: 1;
    radius: 16;
}}

Container.gs-workspace-root {{
    background_color: {canvas};
}}

Container.gs-page-root {{
    background_color: {canvas};
}}

Container.gs-sidebar {{
    background_color: {canvas};
}}

Container.gs-message-user {{
    translate_x: 4;
}}

Container.gs-message-assistant {{
    translate_x: -4;
}}

Surface.gs-message-user {{
    background_color: {palette.get("user_bg", surface_alt)};
    border_color: {with_alpha(accent, 0.38)};
    border_width: 1;
    radius: 18;
    shadow: {base_shadow};
}}

Surface.gs-message-assistant {{
    background_color: {palette.get("assist_bg", surface)};
    border_color: {border};
    border_width: 1;
    radius: 18;
    shadow: {base_shadow};
}}

ArtifactCard.gs-session-item,
ArtifactCard.gs-artifact {{
    background_color: {surface};
    border_color: {border};
    border_width: 1;
    radius: 18;
    shadow: {base_shadow};
}}

ArtifactCard.gs-session-item-active,
ArtifactCard.gs-artifact-active {{
    background_color: {palette.get("active_bg", surface_alt)};
    border_color: {palette.get("active_border", accent)};
    border_width: 1;
    radius: 18;
    shadow: {hover_shadow};
}}

Button.gs-sidebar-item,
Button.gs-tab {{
    background_color: {surface};
    border_color: {border};
    border_width: 1;
    text_color: {text};
    label_text_color: {text};
    radius: 12;
    shadow: {base_shadow};
}}

Button.gs-sidebar-item:hover,
Button.gs-tab:hover {{
    background_color: {surface_alt};
    border_color: {accent};
}}

Button.gs-sidebar-item-active,
Button.gs-tab-active {{
    background_color: {palette.get("active_bg", surface_alt)};
    border_color: {palette.get("active_border", accent)};
    border_width: 1;
    text_color: {palette.get("active_text", text)};
    label_text_color: {palette.get("active_text", text)};
    radius: 12;
    shadow: {hover_shadow};
}}

GlyphButton.gs-rail-active {{
    background_color: {surface_alt};
    border_color: {accent};
    border_width: 1;
    color: {accent};
    shadow: {hover_shadow};
}}

Button.gs-terminal-button {{
    background_color: {surface_alt};
    border_color: {border};
    border_width: 1;
    text_color: {text};
    label_text_color: {text};
    radius: 10;
}}

Button.gs-terminal-button:hover {{
    background_color: {surface};
    border_color: {accent};
}}

Button.gs-terminal-primary {{
    background_color: {accent};
    border_color: {accent};
    border_width: 1;
    text_color: {on_accent};
    label_text_color: {on_accent};
    radius: 10;
    shadow: {accent_shadow};
}}

Select.gs-terminal-input,
TextField.gs-terminal-input,
TextArea.gs-terminal-input {{
    background_color: {surface_alt};
    border_color: {border};
    border_width: 1;
    radius: 10;
    text_color: {text};
    label_text_color: {muted};
    helper_text_color: {muted};
    placeholder_text_color: {with_alpha(text, 0.54)};
}}

Surface.gs-terminal-header,
Surface.gs-terminal-body,
Surface.gs-terminal-composer {{
    background_color: {surface};
    border_color: {border};
    border_width: 1;
    radius: 10;
    shadow: {base_shadow};
}}

Surface.gs-terminal-composer {{
    gradient: {_gradient([surface_alt, surface], begin="top_left", end="bottom_right")};
}}

Button.gs-editor-line,
Button.gs-minimap-line {{
    background_color: transparent;
    border_width: 0;
    text_color: {muted};
    label_text_color: {muted};
    radius: 0;
}}

Button.gs-editor-line-active,
Button.gs-minimap-line-active {{
    background_color: {with_alpha(accent, 0.22)};
    border_width: 0;
    text_color: {text_on(accent)};
    label_text_color: {text_on(accent)};
    radius: 8;
}}

Overlay {{
    scrim_color: {overlay};
}}

Text.gs-muted {{
    color: {muted};
}}

Text.gs-accent {{
    color: {accent};
}}

Text.gs-strong {{
    color: {text};
}}

Text.gs-chip {{
    color: {hero_scrim};
}}

Surface.gs-astrea-hero {{
    background_color: {surface};
    border_color: {border};
    border_width: 1;
    radius: 22;
    shadow: {panel_shadow};
    backdrop_blur: {22 if glass else 10};
}}

Surface.gs-astrea-panel,
Surface.gs-astrea-preview,
Surface.gs-astrea-console,
Surface.gs-astrea-sidebar-card,
Surface.gs-astrea-output-item,
Surface.gs-astrea-metric,
Surface.gs-astrea-stage,
Surface.gs-astrea-config-item,
Surface.gs-astrea-tab-shell,
Surface.gs-astrea-command-bar,
Surface.gs-astrea-activity {{
    background_color: {surface_alt};
    border_color: {border};
    border_width: 1;
    radius: 18;
    shadow: {base_shadow};
    backdrop_blur: {18 if glass else 8};
}}

Tabs.gs-astrea-page-tabs,
Tabs.gs-astrea-type-tabs,
Tabs.gs-astrea-sidebar-tabs {{
    background_color: {surface_alt};
    border_color: {border};
    border_width: 1;
    radius: 16;
    shadow: {base_shadow};
}}

Container.gs-astrea-image-frame {{
    background_color: {surface};
    border_color: {border};
    border_width: 1;
    radius: 18;
    padding: 12;
}}

Surface.gs-astrea-pill {{
    background_color: {surface_alt};
    border_color: {border};
    border_width: 1;
    radius: 999;
}}

Button.gs-astrea-primary {{
    background_color: {accent};
    border_color: {accent};
    border_width: 1;
    text_color: {on_accent};
    label_text_color: {on_accent};
    radius: 12;
    shadow: {accent_shadow};
}}

Button.gs-astrea-primary:hover {{
    background_color: {mix(accent, "#FFFFFF", 0.18)};
}}

Button.gs-astrea-secondary {{
    background_color: {surface};
    border_color: {border};
    border_width: 1;
    text_color: {text};
    label_text_color: {text};
    radius: 12;
}}

Button.gs-astrea-secondary:hover {{
    background_color: {surface_alt};
    border_color: {accent};
}}

Button.gs-astrea-mode {{
    background_color: {surface};
    border_color: {border};
    border_width: 1;
    text_color: {text};
    label_text_color: {text};
    radius: 12;
    shadow: {base_shadow};
}}

Button.gs-astrea-mode:hover {{
    background_color: {surface_alt};
    border_color: {accent};
}}

Button.gs-astrea-mode-active {{
    background_color: {palette.get("active_bg", surface_alt)};
    border_color: {palette.get("active_border", accent)};
    border_width: 1;
    text_color: {palette.get("active_text", text)};
    label_text_color: {palette.get("active_text", text)};
    radius: 12;
    shadow: {hover_shadow};
}}

Button.gs-astrea-page-tab,
Button.gs-astrea-type-tab {{
    background_color: {surface};
    border_color: {border};
    border_width: 1;
    text_color: {text};
    label_text_color: {text};
    radius: 12;
    shadow: {base_shadow};
}}

Button.gs-astrea-page-tab:hover,
Button.gs-astrea-type-tab:hover {{
    background_color: {surface_alt};
    border_color: {accent};
}}

Button.gs-astrea-page-tab-active,
Button.gs-astrea-type-tab-active {{
    background_color: {palette.get("active_bg", surface_alt)};
    border_color: {palette.get("active_border", accent)};
    border_width: 1;
    text_color: {palette.get("active_text", text)};
    label_text_color: {palette.get("active_text", text)};
    radius: 12;
    shadow: {hover_shadow};
}}

Button.gs-astrea-danger {{
    background_color: {with_alpha(error, 0.10)};
    border_color: {with_alpha(error, 0.36)};
    border_width: 1;
    text_color: {error};
    label_text_color: {error};
    radius: 12;
}}

Button.gs-astrea-danger:hover {{
    background_color: {with_alpha(error, 0.18)};
    border_color: {error};
}}

TextField.gs-astrea-input,
TextArea.gs-astrea-input,
Select.gs-astrea-input {{
    background_color: {input_bg};
    border_color: {border};
    border_width: 1;
    radius: 12;
    text_color: {text};
    label_text_color: {muted};
    helper_text_color: {muted};
    placeholder_text_color: {with_alpha(text, 0.54)};
    shadow: {input_shadow};
}}

Surface.gs-astrea-console-shell {{
    background_color: {surface_alt};
    border_color: {border};
    border_width: 1;
    radius: 22;
    shadow: {drawer_shadow};
    backdrop_blur: {24 if glass else 10};
}}
""".strip()
