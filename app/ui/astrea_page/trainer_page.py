from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import butterflyui as ui

from .common import (
    expanded_row,
    make_input,
    make_select,
    make_switch,
    make_text_area,
    read_bool,
    read_value,
    set_select_options,
    split_lines,
    stage_card,
)


class TrainerPage:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        self._palette: dict[str, str] | None = None
        self._glass_mode = False
        self._capabilities: dict[str, Any] = {}
        self._training_type = "lora"
        self._console_open = False

        self._on_train: Callable[[dict[str, Any]], None] | None = None
        self._on_stop: Callable[[], None] | None = None

        self.title = ui.Text("Trainer", class_name="type-heading-lg")
        self.subtitle = ui.Text(
            "Kohya-style training tabs, grouped sd-scripts controls, and a slide-up console for live runs.",
            class_name="type-body-sm gs-muted",
        )
        self.script_hint = ui.Text("Select a training path to map Astrea to the right sd-scripts entrypoint.", class_name="type-caption gs-muted")
        self.dreambooth_button = ui.Button("DreamBooth", class_name="gs-button gs-astrea-type-tab")
        self.lora_button = ui.Button("LoRA", class_name="gs-button gs-astrea-type-tab gs-astrea-type-tab-active")
        self.embedding_button = ui.Button("Embedding", class_name="gs-button gs-astrea-type-tab")
        self.finetune_button = ui.Button("Finetuning", class_name="gs-button gs-astrea-type-tab")

        self.workflow = make_select("Workflow", "base")
        self.model_path = make_input("Base model path", "Checkpoint, diffusers folder, or safetensors source.")
        self.dataset_config = make_input("Dataset config", "Optional .toml config if you already authored one.")
        self.train_data_dir = make_input("Train data directory", "Folder with images for training.")
        self.reg_data_dir = make_input("Regularization directory", "Optional reg images for DreamBooth.")
        self.metadata_json = make_input("Metadata JSON", "Optional captions metadata JSON for finetuning.")
        self.output_dir = make_input("Output directory", str((workspace_root / "genesis" / "astrea" / "outputs" / "training").resolve()))
        self.output_name = make_input("Output name", "astrea_training_run")
        self.precision = make_select("Precision", "fp16")
        self.attention = make_select("Attention backend", "sdpa")
        self.save_model_as = make_select(
            "Save format",
            "safetensors",
            [
                {"label": "Safetensors", "value": "safetensors"},
                {"label": "Checkpoint", "value": "ckpt"},
                {"label": "PyTorch", "value": "pt"},
                {"label": "Diffusers", "value": "diffusers"},
                {"label": "Diffusers Safetensors", "value": "diffusers_safetensors"},
            ],
        )

        self.resolution = make_input("Resolution", "1024,1024")
        self.train_batch_size = make_input("Train batch size", "1")
        self.epochs = make_input("Epochs", "10")
        self.max_train_steps = make_input("Max train steps", "")
        self.gradient_accumulation = make_input("Gradient accumulation", "1")
        self.save_every_n_epochs = make_input("Save every n epochs", "1")
        self.save_every_n_steps = make_input("Save every n steps", "")
        self.seed = make_input("Seed", "")
        self.clip_skip = make_input("CLIP skip", "")
        self.vae_path = make_input("VAE path", "")

        self.learning_rate = make_input("Learning rate", "0.0001")
        self.unet_lr = make_input("UNet LR", "")
        self.text_encoder_lr = make_input("Text encoder LR", "1e-5")
        self.text_encoder_lr1 = make_input("Text encoder LR 1", "1e-5")
        self.text_encoder_lr2 = make_input("Text encoder LR 2", "1e-5")
        self.learning_rate_te = make_input("TE LR (full tune)", "")
        self.learning_rate_te1 = make_input("TE1 LR", "")
        self.learning_rate_te2 = make_input("TE2 LR", "")
        self.optimizer_type = make_input("Optimizer", "AdamW8bit")
        self.optimizer_args = make_text_area("Optimizer args", "CLI fragments such as weight_decay=0.01", min_lines=2, max_lines=4)
        self.lr_scheduler = make_input("LR scheduler", "constant")
        self.lr_warmup_steps = make_input("Warmup steps", "0")
        self.lr_scheduler_num_cycles = make_input("Scheduler cycles", "1")
        self.max_grad_norm = make_input("Max grad norm", "1.0")

        self.network_module = make_input("Network module", "networks.lora")
        self.network_dim = make_input("Network dim", "16")
        self.network_alpha = make_input("Network alpha", "16")
        self.network_dropout = make_input("Network dropout", "")
        self.network_weights = make_input("Network weights", "")
        self.network_args = make_text_area("Network args", "CLI fragments such as conv_dim=8", min_lines=2, max_lines=4)
        self.base_weights = make_text_area("Base weights", "Merge LoRA or LyCORIS weights before training, one path per line.", min_lines=2, max_lines=4)
        self.base_weights_multiplier = make_text_area("Base weight multipliers", "Optional multiplier per line.", min_lines=2, max_lines=4)

        self.caption_extension = make_input("Caption extension", ".txt")
        self.caption_separator = make_input("Caption separator", ",")
        self.dataset_repeats = make_input("Dataset repeats", "10")
        self.keep_tokens = make_input("Keep tokens", "1")
        self.caption_prefix = make_input("Caption prefix", "")
        self.caption_suffix = make_input("Caption suffix", "")
        self.min_bucket_reso = make_input("Min bucket", "256")
        self.max_bucket_reso = make_input("Max bucket", "2048")
        self.bucket_reso_steps = make_input("Bucket steps", "64")
        self.prior_loss_weight = make_input("Prior loss weight", "1.0")
        self.stop_text_encoder_training = make_input("Stop TE at step", "")
        self.training_comment = make_input("Training comment", "")
        self.logging_dir = make_input("Logging directory", "")
        self.log_with = make_select(
            "Log with",
            "tensorboard",
            [
                {"label": "TensorBoard", "value": "tensorboard"},
                {"label": "Weights & Biases", "value": "wandb"},
                {"label": "Both", "value": "all"},
            ],
        )
        self.validation_split = make_input("Validation split", "")
        self.validate_every_n_steps = make_input("Validate every n steps", "")
        self.validate_every_n_epochs = make_input("Validate every n epochs", "")
        self.max_validation_steps = make_input("Max validation steps", "")

        self.token_string = make_input("Token string", "")
        self.init_word = make_input("Init word", "")
        self.num_vectors_per_token = make_input("Vectors per token", "1")
        self.embedding_weights = make_input("Embedding weights", "")

        self.gradient_checkpointing = make_switch("Gradient checkpointing", True)
        self.cache_latents = make_switch("Cache latents", True)
        self.cache_latents_to_disk = make_switch("Cache latents to disk", False)
        self.cache_text_encoder_outputs = make_switch("Cache text encoder outputs", True)
        self.shuffle_caption = make_switch("Shuffle captions", True)
        self.enable_bucket = make_switch("Enable buckets", True)
        self.bucket_no_upscale = make_switch("Bucket no upscale", True)
        self.color_aug = make_switch("Color aug", False)
        self.flip_aug = make_switch("Flip aug", False)
        self.random_crop = make_switch("Random crop", False)
        self.no_half_vae = make_switch("No half VAE", False)
        self.v2 = make_switch("SD 2.x / v2", False)
        self.v_parameterization = make_switch("V-parameterization", False)
        self.network_train_unet_only = make_switch("UNet only", False)
        self.network_train_text_encoder_only = make_switch("Text encoder only", False)
        self.train_text_encoder = make_switch("Train text encoder", False)
        self.no_token_padding = make_switch("No token padding", False)
        self.use_object_template = make_switch("Object template", False)
        self.use_style_template = make_switch("Style template", False)
        self.cpu_offload_checkpointing = make_switch("CPU offload checkpointing", False)

        self.additional_args = make_text_area("Additional sd-scripts args", "--sample_every_n_steps 200", min_lines=3, max_lines=6)

        self.train_button = ui.Button("Train LoRA", class_name="gs-button gs-primary gs-astrea-primary")
        self.stop_button = ui.Button("Stop", class_name="gs-button gs-outline gs-astrea-danger")
        self.console_toggle_button = ui.Button("^ Console", class_name="gs-button gs-outline gs-astrea-secondary")
        self.console_status = ui.Text("Trainer console ready.", class_name="type-caption gs-muted")
        self.console_log = ui.MarkdownView(value="```text\nTrainer console ready.\n```", selectable=True, scrollable=True)
        self.console_close_button = ui.Button("Close", class_name="gs-button gs-outline gs-astrea-secondary")
        self._dreambooth_specific = ui.Container(self._build_dreambooth_specific(), visible=False, opacity=0.0, animate=True, duration_ms=180)
        self._lora_specific = ui.Container(self._build_lora_specific(), visible=True, opacity=1.0, animate=True, duration_ms=180)
        self._embedding_specific = ui.Container(self._build_embedding_specific(), visible=False, opacity=0.0, animate=True, duration_ms=180)
        self._finetune_specific = ui.Container(self._build_finetune_specific(), visible=False, opacity=0.0, animate=True, duration_ms=180)

        self.console_drawer = ui.Drawer(
            ui.Surface(
                ui.Column(
                    ui.Row(
                        ui.Column(
                            ui.Text("Training Console", class_name="type-heading-md"),
                            self.console_status,
                            spacing=4,
                        ),
                        ui.Spacer(),
                        self.console_close_button,
                        spacing=12,
                        cross_axis="center",
                    ),
                    ui.Container(self.console_log, expand=True, padding={"top": 12}),
                    spacing=0,
                    expand=True,
                ),
                padding=18,
                class_name="gs-drawer gs-astrea-console-shell",
                radius=22,
            ),
            open=False,
            side="bottom",
            size=360,
            dismissible=True,
            events=["close"],
            class_name="gs-astrea-console-drawer",
        )

    def bind_events(
        self,
        session: Any,
        *,
        on_train: Callable[[dict[str, Any]], None] | None = None,
        on_stop: Callable[[], None] | None = None,
    ) -> None:
        self._on_train = on_train
        self._on_stop = on_stop

        self.dreambooth_button.on_click(session, lambda _e: self._set_training_type("dreambooth"))
        self.lora_button.on_click(session, lambda _e: self._set_training_type("lora"))
        self.embedding_button.on_click(session, lambda _e: self._set_training_type("embedding"))
        self.finetune_button.on_click(session, lambda _e: self._set_training_type("finetuning"))
        self.train_button.on_click(session, self._handle_train)
        self.stop_button.on_click(session, self._handle_stop)
        self.console_toggle_button.on_click(session, self._toggle_console)
        self.console_close_button.on_click(session, self._close_console)
        self.console_drawer.on_event(session, "close", self._handle_drawer_closed)

    def build(self) -> ui.Control:
        type_rail = ui.Surface(
            ui.Column(
                self.title,
                self.subtitle,
                self.script_hint,
                ui.Row(
                    self.dreambooth_button,
                    self.lora_button,
                    self.embedding_button,
                    self.finetune_button,
                    spacing=8,
                    wrap=True,
                ),
                spacing=10,
            ),
            padding=16,
            class_name="gs-card gs-astrea-tab-shell",
            radius=18,
        )

        accordion = ui.Accordion(
            self._build_project_section(),
            self._build_core_section(),
            self._build_optimizer_section(),
            self._build_dataset_section(),
            self._build_memory_section(),
            self._build_validation_section(),
            self._build_extra_section(),
            labels=[
                "Run Profile",
                "Core Training",
                "Optimizer & Scheduler",
                "Dataset & Captions",
                "Memory & Execution",
                "Validation & Metadata",
                "Raw sd-scripts Args",
            ],
            index=[0, 1, 4],
            multiple=True,
            allow_empty=True,
            spacing=10,
            class_name="gs-astrea-accordion",
        )

        command_bar = ui.Surface(
            ui.Row(
                self.train_button,
                self.stop_button,
                ui.Spacer(),
                self.console_toggle_button,
                spacing=10,
                cross_axis="center",
            ),
            padding=14,
            class_name="gs-card gs-astrea-command-bar",
            radius=18,
        )

        content = ui.Container(
            ui.ScrollableColumn(
                spacing=12,
                expand=True,
                content_padding={"left": 2, "right": 2, "top": 4, "bottom": 4},
                controls=[type_rail, self._build_specific_section(), accordion, command_bar],
            ),
            expand=True,
        )

        self._set_training_type(self._training_type)
        return ui.Stack(content, self.console_drawer, fit="expand", expand=True)

    def apply_capabilities(self, capabilities: dict[str, Any]) -> None:
        self._capabilities = capabilities if isinstance(capabilities, dict) else {}
        workflows = self._capabilities.get("train_workflows", [])
        workflow_values = [str(item.get("value", "")).strip() for item in workflows if isinstance(item, dict) and str(item.get("value", "")).strip()]
        if workflow_values:
            set_select_options(self.workflow, workflow_values, fallback="base")
        set_select_options(self.precision, self._capabilities.get("precisions", []), fallback="fp16")
        set_select_options(self.attention, self._capabilities.get("attention_backends", []), fallback="sdpa")
        self._sync_script_hint()

    def set_snapshot(self, snapshot: dict[str, Any]) -> None:
        busy = bool(snapshot.get("busy"))
        train_label = {
            "dreambooth": "DreamBooth",
            "lora": "LoRA",
            "embedding": "Embedding",
            "finetuning": "Finetuning",
        }.get(self._training_type, "LoRA")
        self.train_button.patch(text=f"Train {train_label}", disabled=busy)
        self.stop_button.patch(disabled=not busy)

        job_kind = str(snapshot.get("job_kind", "") or "").strip()
        job_title = str(snapshot.get("job_title", "") or "").strip()
        if busy and job_title:
            self.console_status.patch(text=f"{job_kind.title()} live: {job_title}")
        elif busy:
            self.console_status.patch(text="Training process active.")
        else:
            self.console_status.patch(text="Trainer console ready.")

        logs_value = str(snapshot.get("logs", "")).rstrip() or "Trainer console ready."
        self.console_log.patch(value=f"```text\n{logs_value}\n```")

    def set_palette(self, palette: dict[str, str]) -> None:
        self._palette = palette

    def set_glass_mode(self, enabled: bool) -> None:
        self._glass_mode = bool(enabled)

    def collect_config(self) -> dict[str, Any]:
        return {
            "train_type": self._training_type,
            "workflow": read_value(self.workflow),
            "model_path": read_value(self.model_path),
            "dataset_config": read_value(self.dataset_config),
            "train_data_dir": read_value(self.train_data_dir),
            "reg_data_dir": read_value(self.reg_data_dir),
            "metadata_json": read_value(self.metadata_json),
            "output_dir": read_value(self.output_dir),
            "output_name": read_value(self.output_name),
            "precision": read_value(self.precision),
            "attention": read_value(self.attention),
            "save_model_as": read_value(self.save_model_as),
            "resolution": read_value(self.resolution),
            "train_batch_size": read_value(self.train_batch_size),
            "epochs": read_value(self.epochs),
            "max_train_steps": read_value(self.max_train_steps),
            "gradient_accumulation_steps": read_value(self.gradient_accumulation),
            "save_every_n_epochs": read_value(self.save_every_n_epochs),
            "save_every_n_steps": read_value(self.save_every_n_steps),
            "seed": read_value(self.seed),
            "clip_skip": read_value(self.clip_skip),
            "vae_path": read_value(self.vae_path),
            "learning_rate": read_value(self.learning_rate),
            "unet_lr": read_value(self.unet_lr),
            "text_encoder_lr": read_value(self.text_encoder_lr),
            "text_encoder_lr1": read_value(self.text_encoder_lr1),
            "text_encoder_lr2": read_value(self.text_encoder_lr2),
            "learning_rate_te": read_value(self.learning_rate_te),
            "learning_rate_te1": read_value(self.learning_rate_te1),
            "learning_rate_te2": read_value(self.learning_rate_te2),
            "optimizer_type": read_value(self.optimizer_type),
            "optimizer_args": read_value(self.optimizer_args),
            "lr_scheduler": read_value(self.lr_scheduler),
            "lr_warmup_steps": read_value(self.lr_warmup_steps),
            "lr_scheduler_num_cycles": read_value(self.lr_scheduler_num_cycles),
            "max_grad_norm": read_value(self.max_grad_norm),
            "network_module": read_value(self.network_module),
            "network_dim": read_value(self.network_dim),
            "network_alpha": read_value(self.network_alpha),
            "network_dropout": read_value(self.network_dropout),
            "network_weights": read_value(self.network_weights),
            "network_args": read_value(self.network_args),
            "base_weights": split_lines(read_value(self.base_weights)),
            "base_weights_multiplier": split_lines(read_value(self.base_weights_multiplier)),
            "caption_extension": read_value(self.caption_extension),
            "caption_separator": read_value(self.caption_separator),
            "dataset_repeats": read_value(self.dataset_repeats),
            "keep_tokens": read_value(self.keep_tokens),
            "caption_prefix": read_value(self.caption_prefix),
            "caption_suffix": read_value(self.caption_suffix),
            "min_bucket_reso": read_value(self.min_bucket_reso),
            "max_bucket_reso": read_value(self.max_bucket_reso),
            "bucket_reso_steps": read_value(self.bucket_reso_steps),
            "prior_loss_weight": read_value(self.prior_loss_weight),
            "stop_text_encoder_training": read_value(self.stop_text_encoder_training),
            "training_comment": read_value(self.training_comment),
            "logging_dir": read_value(self.logging_dir),
            "log_with": read_value(self.log_with),
            "validation_split": read_value(self.validation_split),
            "validate_every_n_steps": read_value(self.validate_every_n_steps),
            "validate_every_n_epochs": read_value(self.validate_every_n_epochs),
            "max_validation_steps": read_value(self.max_validation_steps),
            "token_string": read_value(self.token_string),
            "init_word": read_value(self.init_word),
            "num_vectors_per_token": read_value(self.num_vectors_per_token),
            "weights": read_value(self.embedding_weights),
            "gradient_checkpointing": read_bool(self.gradient_checkpointing),
            "cache_latents": read_bool(self.cache_latents),
            "cache_latents_to_disk": read_bool(self.cache_latents_to_disk),
            "cache_text_encoder_outputs": read_bool(self.cache_text_encoder_outputs),
            "shuffle_caption": read_bool(self.shuffle_caption),
            "enable_bucket": read_bool(self.enable_bucket),
            "bucket_no_upscale": read_bool(self.bucket_no_upscale),
            "color_aug": read_bool(self.color_aug),
            "flip_aug": read_bool(self.flip_aug),
            "random_crop": read_bool(self.random_crop),
            "no_half_vae": read_bool(self.no_half_vae),
            "v2": read_bool(self.v2),
            "v_parameterization": read_bool(self.v_parameterization),
            "network_train_unet_only": read_bool(self.network_train_unet_only),
            "network_train_text_encoder_only": read_bool(self.network_train_text_encoder_only),
            "train_text_encoder": read_bool(self.train_text_encoder),
            "no_token_padding": read_bool(self.no_token_padding),
            "use_object_template": read_bool(self.use_object_template),
            "use_style_template": read_bool(self.use_style_template),
            "cpu_offload_checkpointing": read_bool(self.cpu_offload_checkpointing),
            "extra_args": read_value(self.additional_args),
        }

    def _build_project_section(self) -> ui.Control:
        return ui.Column(
            self.workflow,
            self.model_path,
            self.dataset_config,
            self.train_data_dir,
            self.reg_data_dir,
            self.metadata_json,
            expanded_row(self.output_dir, self.output_name),
            expanded_row(self.precision, self.attention, self.save_model_as),
            spacing=10,
        )

    def _build_core_section(self) -> ui.Control:
        return ui.Column(
            expanded_row(self.resolution, self.train_batch_size, self.epochs, self.max_train_steps),
            expanded_row(self.gradient_accumulation, self.save_every_n_epochs, self.save_every_n_steps, self.seed),
            expanded_row(self.clip_skip, self.vae_path),
            spacing=10,
        )

    def _build_optimizer_section(self) -> ui.Control:
        return ui.Column(
            expanded_row(self.learning_rate, self.unet_lr, self.text_encoder_lr),
            expanded_row(self.text_encoder_lr1, self.text_encoder_lr2, self.learning_rate_te),
            expanded_row(self.learning_rate_te1, self.learning_rate_te2, self.optimizer_type),
            expanded_row(self.lr_scheduler, self.lr_warmup_steps, self.lr_scheduler_num_cycles, self.max_grad_norm),
            self.optimizer_args,
            spacing=10,
        )

    def _build_dataset_section(self) -> ui.Control:
        return ui.Column(
            expanded_row(self.caption_extension, self.caption_separator, self.dataset_repeats, self.keep_tokens),
            expanded_row(self.caption_prefix, self.caption_suffix),
            expanded_row(self.min_bucket_reso, self.max_bucket_reso, self.bucket_reso_steps),
            ui.Row(self.shuffle_caption, self.enable_bucket, self.bucket_no_upscale, spacing=18),
            ui.Row(self.color_aug, self.flip_aug, self.random_crop, spacing=18),
            spacing=10,
        )

    def _build_memory_section(self) -> ui.Control:
        return ui.Column(
            ui.Row(self.gradient_checkpointing, self.cache_latents, self.cache_latents_to_disk, spacing=18),
            ui.Row(self.cache_text_encoder_outputs, self.no_half_vae, self.cpu_offload_checkpointing, spacing=18),
            ui.Row(self.v2, self.v_parameterization, self.train_text_encoder, spacing=18),
            spacing=10,
        )

    def _build_specific_section(self) -> ui.Control:
        return ui.Stack(
            self._dreambooth_specific,
            self._lora_specific,
            self._embedding_specific,
            self._finetune_specific,
            fit="expand",
            expand=True,
        )

    def _build_validation_section(self) -> ui.Control:
        return ui.Column(
            expanded_row(self.prior_loss_weight, self.stop_text_encoder_training, self.training_comment),
            expanded_row(self.logging_dir, self.log_with),
            expanded_row(self.validation_split, self.validate_every_n_steps, self.validate_every_n_epochs, self.max_validation_steps),
            spacing=10,
        )

    def _build_extra_section(self) -> ui.Control:
        return ui.Column(self.additional_args, spacing=10)

    def _build_lora_specific(self) -> ui.Control:
        return stage_card(
            "LoRA Controls",
            "Rank, alpha, preload weights, and constrain which parts of the model should actually move.",
            ui.Column(
                expanded_row(self.network_module, self.network_dim, self.network_alpha, self.network_dropout),
                expanded_row(self.network_weights),
                self.network_args,
                self.base_weights,
                self.base_weights_multiplier,
                ui.Row(self.network_train_unet_only, self.network_train_text_encoder_only, spacing=18),
                spacing=10,
            ),
        )

    def _build_dreambooth_specific(self) -> ui.Control:
        return stage_card(
            "DreamBooth Controls",
            "Keep the regularization path explicit and expose the text encoder pacing knobs Kohya users expect.",
            ui.Column(
                expanded_row(self.reg_data_dir, self.prior_loss_weight, self.stop_text_encoder_training),
                ui.Row(self.no_token_padding, self.train_text_encoder, spacing=18),
                spacing=10,
            ),
        )

    def _build_embedding_specific(self) -> ui.Control:
        return stage_card(
            "Embedding Controls",
            "Textual inversion needs token setup, vector count, and template behavior more than network rank tuning.",
            ui.Column(
                expanded_row(self.token_string, self.init_word, self.num_vectors_per_token),
                expanded_row(self.embedding_weights),
                ui.Row(self.use_object_template, self.use_style_template, spacing=18),
                spacing=10,
            ),
        )

    def _build_finetune_specific(self) -> ui.Control:
        return stage_card(
            "Finetuning Controls",
            "Full finetune runs lean on metadata JSON, optional text encoder training, and explicit learning-rate splits.",
            ui.Column(
                expanded_row(self.metadata_json, self.learning_rate_te, self.learning_rate_te1, self.learning_rate_te2),
                ui.Row(self.train_text_encoder, spacing=18),
                spacing=10,
            ),
        )

    def _set_training_type(self, training_type: str) -> None:
        self._training_type = training_type if training_type in {"dreambooth", "lora", "embedding", "finetuning"} else "lora"
        active = "gs-button gs-astrea-type-tab gs-astrea-type-tab-active"
        idle = "gs-button gs-astrea-type-tab"
        self.dreambooth_button.patch(class_name=active if self._training_type == "dreambooth" else idle)
        self.lora_button.patch(class_name=active if self._training_type == "lora" else idle)
        self.embedding_button.patch(class_name=active if self._training_type == "embedding" else idle)
        self.finetune_button.patch(class_name=active if self._training_type == "finetuning" else idle)
        self._dreambooth_specific.patch(visible=self._training_type == "dreambooth", opacity=1.0 if self._training_type == "dreambooth" else 0.0)
        self._lora_specific.patch(visible=self._training_type == "lora", opacity=1.0 if self._training_type == "lora" else 0.0)
        self._embedding_specific.patch(visible=self._training_type == "embedding", opacity=1.0 if self._training_type == "embedding" else 0.0)
        self._finetune_specific.patch(visible=self._training_type == "finetuning", opacity=1.0 if self._training_type == "finetuning" else 0.0)
        self.train_button.patch(text=f"Train {self._training_type_label(self._training_type)}")
        self._sync_script_hint()

    def _training_type_label(self, training_type: str) -> str:
        return {
            "dreambooth": "DreamBooth",
            "lora": "LoRA",
            "embedding": "Embedding",
            "finetuning": "Finetuning",
        }.get(training_type, "LoRA")

    def _sync_script_hint(self) -> None:
        workflow = read_value(self.workflow) or "base"
        if self._training_type == "dreambooth":
            script = "sdxl_train.py" if workflow == "sdxl" else "train_db.py"
            hint = "DreamBooth profile with regularization images and text-encoder pacing."
        elif self._training_type == "embedding":
            script = "sdxl_train_textual_inversion.py" if workflow == "sdxl" else "train_textual_inversion.py"
            hint = "Textual inversion profile with token authoring and template controls."
        elif self._training_type == "finetuning":
            script = "sdxl_train.py" if workflow == "sdxl" else "fine_tune.py"
            hint = "Full finetuning profile with metadata JSON support and broader training surface."
        else:
            script = "sdxl_train_network.py" if workflow == "sdxl" else "train_network.py"
            hint = "LoRA network training profile with rank, alpha, and network module controls."
        self.script_hint.patch(text=f"{hint} Launch target: {script}")

    def _toggle_console(self, _event: Any = None) -> None:
        self._console_open = not self._console_open
        self.console_drawer.patch(open=self._console_open)

    def _close_console(self, _event: Any = None) -> None:
        self._console_open = False
        self.console_drawer.patch(open=False)

    def _handle_drawer_closed(self, _event: Any = None) -> None:
        self._console_open = False

    def _handle_train(self, _event: Any = None) -> None:
        if callable(self._on_train):
            self._on_train(self.collect_config())

    def _handle_stop(self, _event: Any = None) -> None:
        if callable(self._on_stop):
            self._on_stop()
