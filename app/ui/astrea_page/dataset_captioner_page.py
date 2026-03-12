from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import butterflyui as ui

from .common import expanded_row, make_input, make_select, make_switch, make_text_area, read_bool, read_value, stage_card


class DatasetCaptionerPage:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        self._palette: dict[str, str] | None = None
        self._glass_mode = False
        self._caption_mode = "blip"

        self._on_caption: Callable[[dict[str, Any]], None] | None = None
        self._on_build_dataset: Callable[[dict[str, Any]], None] | None = None
        self._on_stop: Callable[[], None] | None = None

        self.header = ui.Text("Dataset Captioner", class_name="type-heading-lg")
        self.subheader = ui.Text(
            "Build captions or tags first, then export a dataset config without leaving Astrea.",
            class_name="type-body-sm gs-muted",
        )
        self.status_note = ui.Text("BLIP mode is selected for natural-language captions.", class_name="type-caption gs-muted")
        self.blip_button = ui.Button("BLIP", class_name="gs-button gs-astrea-type-tab gs-astrea-type-tab-active")
        self.wd14_button = ui.Button("WD14 Tagger", class_name="gs-button gs-astrea-type-tab")

        self.image_dir = make_input("Image directory", "Folder with images to caption or tag.")
        self.output_path = make_input("Output path", "Optional JSON output path for WD14.")
        self.caption_extension = make_input("Caption extension", ".txt")
        self.batch_size = make_input("Batch size", "1")
        self.max_workers = make_input("Data loader workers", "")
        self.caption_weights = make_input("BLIP caption weights", "model_large_caption.pth or URL.")
        self.num_beams = make_input("Beam count", "1")
        self.top_p = make_input("Top-p", "0.9")
        self.max_length = make_input("Max length", "75")
        self.min_length = make_input("Min length", "5")
        self.seed = make_input("Seed", "42")

        self.repo_id = make_input("WD14 repo id", "SmilingWolf/wd-v1-4-convnextv2-tagger-v2")
        self.model_dir = make_input("WD14 model dir", "wd14_tagger_model")
        self.thresh = make_input("Threshold", "0.35")
        self.general_threshold = make_input("General threshold", "")
        self.character_threshold = make_input("Character threshold", "")
        self.always_first_tags = make_input("Always-first tags", "")
        self.undesired_tags = make_input("Undesired tags", "")
        self.caption_separator = make_input("Caption separator", ", ")
        self.tag_replacement = make_text_area("Tag replacement", "source,target;source2,target2", min_lines=2, max_lines=4)

        self.dataset_name = make_input("Dataset name", "astrea_dataset")
        self.dataset_output_path = make_input("Config output path", "")
        self.dataset_resolution = make_input("Resolution", "1024,1024")
        self.dataset_batch_size = make_input("Config batch size", "1")
        self.dataset_repeats = make_input("Repeats", "10")
        self.dataset_caption_extension = make_input("Config caption extension", ".txt")
        self.dataset_class_tokens = make_input("Class tokens", "")
        self.dataset_keep_tokens = make_input("Keep tokens", "1")
        self.dataset_min_bucket = make_input("Min bucket", "256")
        self.dataset_max_bucket = make_input("Max bucket", "2048")
        self.dataset_caption_prefix = make_input("Caption prefix", "")
        self.dataset_caption_suffix = make_input("Caption suffix", "")

        self.recursive = make_switch("Recursive", True)
        self.beam_search = make_switch("Beam search", False)
        self.force_download = make_switch("Force download", False)
        self.remove_underscore = make_switch("Remove underscore", True)
        self.append_tags = make_switch("Append tags", False)
        self.use_rating_tags = make_switch("Rating tags first", False)
        self.use_quality_tags = make_switch("Quality tags first", False)
        self.character_tags_first = make_switch("Character tags first", False)
        self.frequency_tags = make_switch("Show frequency tags", False)
        self.onnx = make_switch("Use ONNX", False)
        self.dataset_shuffle = make_switch("Shuffle captions", True)
        self.dataset_enable_bucket = make_switch("Enable buckets", True)
        self.dataset_bucket_no_upscale = make_switch("Bucket no upscale", True)

        self.extra_args = make_text_area("Additional caption args", "--debug", min_lines=2, max_lines=5)

        self.caption_button = ui.Button("Caption Dataset", class_name="gs-button gs-primary gs-astrea-primary")
        self.build_config_button = ui.Button("Build Dataset Config", class_name="gs-button gs-outline gs-astrea-secondary")
        self.stop_button = ui.Button("Stop", class_name="gs-button gs-outline gs-astrea-danger")
        self._blip_section = ui.Container(self._build_blip_section(), visible=True, opacity=1.0, animate=True, duration_ms=180)
        self._wd14_section = ui.Container(self._build_wd14_section(), visible=False, opacity=0.0, animate=True, duration_ms=180)

    def bind_events(
        self,
        session: Any,
        *,
        on_caption: Callable[[dict[str, Any]], None] | None = None,
        on_build_dataset: Callable[[dict[str, Any]], None] | None = None,
        on_stop: Callable[[], None] | None = None,
    ) -> None:
        self._on_caption = on_caption
        self._on_build_dataset = on_build_dataset
        self._on_stop = on_stop

        self.blip_button.on_click(session, lambda _e: self._set_caption_mode("blip"))
        self.wd14_button.on_click(session, lambda _e: self._set_caption_mode("wd14"))
        self.caption_button.on_click(session, self._handle_caption)
        self.build_config_button.on_click(session, self._handle_build_dataset)
        self.stop_button.on_click(session, self._handle_stop)

    def build(self) -> ui.Control:
        self._set_caption_mode(self._caption_mode)
        return ui.ScrollableColumn(
            spacing=12,
            expand=True,
            content_padding={"left": 2, "right": 2, "top": 4, "bottom": 4},
            controls=[
                ui.Surface(
                    ui.Column(
                        self.header,
                        self.subheader,
                        self.status_note,
                        ui.Row(self.blip_button, self.wd14_button, spacing=8),
                        spacing=10,
                    ),
                    padding=16,
                    class_name="gs-card gs-astrea-tab-shell",
                    radius=18,
                ),
                stage_card(
                    "Source & Output",
                    "Point Astrea at the image folder once, then steer either natural-language captions or tagger output from there.",
                    ui.Column(
                        self.image_dir,
                        expanded_row(self.output_path, self.caption_extension, self.batch_size, self.max_workers),
                        ui.Row(self.recursive, spacing=18),
                        spacing=10,
                    ),
                ),
                ui.Stack(self._blip_section, self._wd14_section, fit="expand", expand=True),
                stage_card(
                    "Dataset Config Export",
                    "Once the captions look right, stamp a config that can feed the trainer directly.",
                    ui.Column(
                        self.dataset_name,
                        self.dataset_output_path,
                        expanded_row(self.dataset_resolution, self.dataset_batch_size, self.dataset_repeats),
                        expanded_row(self.dataset_caption_extension, self.dataset_class_tokens, self.dataset_keep_tokens),
                        expanded_row(self.dataset_min_bucket, self.dataset_max_bucket),
                        expanded_row(self.dataset_caption_prefix, self.dataset_caption_suffix),
                        ui.Row(self.dataset_shuffle, self.dataset_enable_bucket, self.dataset_bucket_no_upscale, spacing=18),
                        spacing=10,
                    ),
                ),
                stage_card(
                    "Raw Caption Args",
                    "Use this when you want to punch through Astrea and hand sd-scripts extra CLI switches directly.",
                    ui.Column(self.extra_args, spacing=10),
                ),
                ui.Surface(
                    ui.Row(
                        self.caption_button,
                        self.build_config_button,
                        self.stop_button,
                        spacing=10,
                        wrap=True,
                    ),
                    padding=14,
                    class_name="gs-card gs-astrea-command-bar",
                    radius=18,
                ),
            ],
        )

    def set_snapshot(self, snapshot: dict[str, Any]) -> None:
        busy = bool(snapshot.get("busy"))
        self.caption_button.patch(disabled=busy)
        self.build_config_button.patch(disabled=busy)
        self.stop_button.patch(disabled=not busy)
        last_config = str(snapshot.get("last_dataset_config", "") or "").strip()
        if busy:
            self.status_note.patch(text="Captioning or dataset work is running. Recent logs stay in the activity pane.")
        elif last_config:
            self.status_note.patch(text=f"Last dataset config: {Path(last_config).name}")
        else:
            self.status_note.patch(text="BLIP mode is selected for natural-language captions." if self._caption_mode == "blip" else "WD14 mode is selected for tag-style captions.")

    def set_palette(self, palette: dict[str, str]) -> None:
        self._palette = palette

    def set_glass_mode(self, enabled: bool) -> None:
        self._glass_mode = bool(enabled)

    def collect_caption_config(self) -> dict[str, Any]:
        return {
            "caption_mode": self._caption_mode,
            "image_dir": read_value(self.image_dir),
            "output_path": read_value(self.output_path),
            "caption_extension": read_value(self.caption_extension),
            "batch_size": read_value(self.batch_size),
            "max_data_loader_n_workers": read_value(self.max_workers),
            "caption_weights": read_value(self.caption_weights),
            "num_beams": read_value(self.num_beams),
            "top_p": read_value(self.top_p),
            "max_length": read_value(self.max_length),
            "min_length": read_value(self.min_length),
            "seed": read_value(self.seed),
            "repo_id": read_value(self.repo_id),
            "model_dir": read_value(self.model_dir),
            "thresh": read_value(self.thresh),
            "general_threshold": read_value(self.general_threshold),
            "character_threshold": read_value(self.character_threshold),
            "always_first_tags": read_value(self.always_first_tags),
            "undesired_tags": read_value(self.undesired_tags),
            "caption_separator": read_value(self.caption_separator),
            "tag_replacement": read_value(self.tag_replacement),
            "recursive": read_bool(self.recursive),
            "beam_search": read_bool(self.beam_search),
            "force_download": read_bool(self.force_download),
            "remove_underscore": read_bool(self.remove_underscore),
            "append_tags": read_bool(self.append_tags),
            "use_rating_tags": read_bool(self.use_rating_tags),
            "use_quality_tags": read_bool(self.use_quality_tags),
            "character_tags_first": read_bool(self.character_tags_first),
            "frequency_tags": read_bool(self.frequency_tags),
            "onnx": read_bool(self.onnx),
            "extra_args": read_value(self.extra_args),
        }

    def collect_dataset_config(self) -> dict[str, Any]:
        return {
            "name": read_value(self.dataset_name),
            "image_dir": read_value(self.image_dir),
            "output_path": read_value(self.dataset_output_path),
            "resolution": read_value(self.dataset_resolution),
            "batch_size": read_value(self.dataset_batch_size),
            "num_repeats": read_value(self.dataset_repeats),
            "caption_extension": read_value(self.dataset_caption_extension),
            "class_tokens": read_value(self.dataset_class_tokens),
            "keep_tokens": read_value(self.dataset_keep_tokens),
            "min_bucket_reso": read_value(self.dataset_min_bucket),
            "max_bucket_reso": read_value(self.dataset_max_bucket),
            "caption_prefix": read_value(self.dataset_caption_prefix),
            "caption_suffix": read_value(self.dataset_caption_suffix),
            "shuffle_caption": read_bool(self.dataset_shuffle),
            "enable_bucket": read_bool(self.dataset_enable_bucket),
            "bucket_no_upscale": read_bool(self.dataset_bucket_no_upscale),
        }

    def _build_blip_section(self) -> ui.Control:
        return stage_card(
            "BLIP Captioning",
            "Generate natural-language captions with beam search or nucleus sampling, then keep the folder ready for training.",
            ui.Column(
                self.caption_weights,
                expanded_row(self.num_beams, self.top_p, self.max_length, self.min_length),
                expanded_row(self.seed),
                ui.Row(self.beam_search, spacing=18),
                spacing=10,
            ),
        )

    def _build_wd14_section(self) -> ui.Control:
        return stage_card(
            "WD14 Tagger",
            "Build tag-driven captions with threshold control, tag ordering, and cleanup rules before export.",
            ui.Column(
                expanded_row(self.repo_id, self.model_dir),
                expanded_row(self.thresh, self.general_threshold, self.character_threshold),
                expanded_row(self.always_first_tags, self.undesired_tags, self.caption_separator),
                self.tag_replacement,
                ui.Row(
                    self.force_download,
                    self.remove_underscore,
                    self.append_tags,
                    self.use_rating_tags,
                    spacing=18,
                    wrap=True,
                ),
                ui.Row(
                    self.use_quality_tags,
                    self.character_tags_first,
                    self.frequency_tags,
                    self.onnx,
                    spacing=18,
                    wrap=True,
                ),
                spacing=10,
            ),
        )

    def _set_caption_mode(self, caption_mode: str) -> None:
        self._caption_mode = "wd14" if caption_mode == "wd14" else "blip"
        active = "gs-button gs-astrea-type-tab gs-astrea-type-tab-active"
        idle = "gs-button gs-astrea-type-tab"
        self.blip_button.patch(class_name=active if self._caption_mode == "blip" else idle)
        self.wd14_button.patch(class_name=active if self._caption_mode == "wd14" else idle)
        self._blip_section.patch(visible=self._caption_mode == "blip", opacity=1.0 if self._caption_mode == "blip" else 0.0)
        self._wd14_section.patch(visible=self._caption_mode == "wd14", opacity=1.0 if self._caption_mode == "wd14" else 0.0)
        self.caption_button.patch(text="Caption Dataset" if self._caption_mode == "blip" else "Tag Dataset")
        self.status_note.patch(text="BLIP mode is selected for natural-language captions." if self._caption_mode == "blip" else "WD14 mode is selected for tag-style captions.")

    def _handle_caption(self, _event: Any = None) -> None:
        if callable(self._on_caption):
            self._on_caption(self.collect_caption_config())

    def _handle_build_dataset(self, _event: Any = None) -> None:
        if callable(self._on_build_dataset):
            self._on_build_dataset(self.collect_dataset_config())

    def _handle_stop(self, _event: Any = None) -> None:
        if callable(self._on_stop):
            self._on_stop()
