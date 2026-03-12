from __future__ import annotations

from typing import Any, Callable

import butterflyui as ui

from .common import expanded_row, make_input, make_select, make_text_area, read_value, set_select_options, split_lines, stage_card


class GeneratorPage:
    def __init__(self) -> None:
        self._palette: dict[str, str] | None = None
        self._glass_mode = False
        self._on_generate: Callable[[dict[str, Any]], None] | None = None

        self.status_note = ui.Text("Prompt a checkpoint, stack optional LoRAs, and render straight from Astrea.", class_name="type-body-sm gs-muted")

        self.workflow = make_select("Workflow", "base")
        self.model_path = make_input("Base model path", "Checkpoint or safetensors file.")
        self.output_dir = make_input("Output directory", "Rendered images are written here.")
        self.prompt = make_text_area("Prompt", "Describe the image you want Astrea to render.", min_lines=4, max_lines=7)
        self.negative_prompt = make_text_area("Negative prompt", "Optional negatives to suppress unwanted traits.")
        self.width = make_input("Width", "1024")
        self.height = make_input("Height", "1024")
        self.steps = make_input("Steps", "28")
        self.guidance_scale = make_input("Guidance scale", "7.5")
        self.batch_size = make_input("Batch size", "1")
        self.images_per_prompt = make_input("Images per prompt", "1")
        self.seed = make_input("Seed", "")
        self.clip_skip = make_input("CLIP skip", "")
        self.precision = make_select("Precision", "fp16")
        self.attention = make_select("Attention backend", "xformers")
        self.sampler = make_input("Sampler", "euler_a")
        self.vae_path = make_input("VAE path", "")
        self.lora_weights = make_text_area("LoRA weights", "One path per line.", min_lines=3, max_lines=5)
        self.lora_multipliers = make_text_area("LoRA multipliers", "Optional multiplier per line, matched by row.", min_lines=2, max_lines=4)
        self.generate_button = ui.Button("Generate Images", class_name="gs-button gs-primary gs-astrea-primary")

    def bind_events(self, session: Any, *, on_generate: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._on_generate = on_generate
        self.generate_button.on_click(session, self._handle_generate)

    def build(self) -> ui.Control:
        return ui.ScrollableColumn(
            spacing=12,
            expand=True,
            content_padding={"left": 2, "right": 2, "top": 4, "bottom": 4},
            controls=[
                stage_card(
                    "Prompt Board",
                    "Drive generation with a dedicated prompt area and negative prompt staging.",
                    ui.Column(
                        self.status_note,
                        self.prompt,
                        self.negative_prompt,
                        spacing=10,
                    ),
                ),
                stage_card(
                    "Model Routing",
                    "Select the workflow, source checkpoint, output target, and inference-time LoRAs.",
                    ui.Column(
                        self.workflow,
                        self.model_path,
                        self.output_dir,
                        self.vae_path,
                        self.lora_weights,
                        self.lora_multipliers,
                        spacing=10,
                    ),
                ),
                stage_card(
                    "Render Controls",
                    "Astrea keeps the fast controls up front while still exposing the sd-scripts switches that matter most for iteration.",
                    ui.Column(
                        expanded_row(self.width, self.height, self.steps, self.guidance_scale),
                        expanded_row(self.batch_size, self.images_per_prompt, self.seed, self.clip_skip),
                        expanded_row(self.precision, self.attention, self.sampler),
                        ui.Row(self.generate_button, spacing=10),
                        spacing=10,
                    ),
                ),
            ],
        )

    def set_snapshot(self, snapshot: dict[str, Any]) -> None:
        busy = bool(snapshot.get("busy"))
        self.generate_button.patch(disabled=busy)
        self.status_note.patch(
            text="Generation is running. Outputs will appear in the side rail." if busy else "Prompt a checkpoint, stack optional LoRAs, and render straight from Astrea."
        )

    def apply_capabilities(self, capabilities: dict[str, Any]) -> None:
        workflows = capabilities.get("generate_workflows", []) if isinstance(capabilities, dict) else []
        workflow_values = [str(item.get("value", "")).strip() for item in workflows if isinstance(item, dict) and str(item.get("value", "")).strip()]
        if workflow_values:
            set_select_options(self.workflow, workflow_values, fallback="base")
        set_select_options(self.precision, capabilities.get("precisions", []), fallback="fp16")
        set_select_options(self.attention, capabilities.get("attention_backends", []), fallback="xformers")

    def set_palette(self, palette: dict[str, str]) -> None:
        self._palette = palette

    def set_glass_mode(self, enabled: bool) -> None:
        self._glass_mode = bool(enabled)

    def collect_config(self) -> dict[str, Any]:
        return {
            "workflow": read_value(self.workflow),
            "model_path": read_value(self.model_path),
            "output_dir": read_value(self.output_dir),
            "prompt": read_value(self.prompt),
            "negative_prompt": read_value(self.negative_prompt),
            "width": read_value(self.width),
            "height": read_value(self.height),
            "steps": read_value(self.steps),
            "guidance_scale": read_value(self.guidance_scale),
            "batch_size": read_value(self.batch_size),
            "images_per_prompt": read_value(self.images_per_prompt),
            "seed": read_value(self.seed),
            "clip_skip": read_value(self.clip_skip),
            "precision": read_value(self.precision),
            "attention": read_value(self.attention),
            "sampler": read_value(self.sampler),
            "vae_path": read_value(self.vae_path),
            "lora_weights": split_lines(read_value(self.lora_weights)),
            "lora_multipliers": split_lines(read_value(self.lora_multipliers)),
        }

    def _handle_generate(self, _event: Any = None) -> None:
        if callable(self._on_generate):
            self._on_generate(self.collect_config())
