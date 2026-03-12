from __future__ import annotations

import os
import shlex
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal


JobKind = Literal["generation", "training", "captioning", "dataset_config"]
WorkflowKind = Literal["base", "sdxl"]
TrainingKind = Literal["dreambooth", "lora", "embedding", "finetuning"]
CaptionMode = Literal["blip", "wd14"]


@dataclass(slots=True)
class AstreaRunRecord:
    kind: JobKind
    title: str
    output_path: str
    status: str


class AstreaService:
    def __init__(self, workspace_root: Path, data_root: Path) -> None:
        self.workspace_root = workspace_root
        self.data_root = data_root
        self.astrea_root = workspace_root / "genesis" / "astrea"
        self.scripts_root = self.astrea_root / "sd-scripts"
        self.configs_root = self.astrea_root / "configs"
        self.python_exe = workspace_root / "env" / "Scripts" / "python.exe"
        self.accelerate_exe = workspace_root / "env" / "Scripts" / "accelerate.exe"
        self.generated_root = self.astrea_root / "outputs" / "generated"
        self.training_root = self.astrea_root / "outputs" / "training"
        self.generated_root.mkdir(parents=True, exist_ok=True)
        self.training_root.mkdir(parents=True, exist_ok=True)
        self.configs_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._job_kind: JobKind | None = None
        self._job_title: str | None = None
        self._log_lines: list[str] = []
        self._recent_runs: list[AstreaRunRecord] = []
        self._on_update: Callable[[dict[str, Any]], None] | None = None
        self._last_dataset_config = ""

    def set_on_update(self, callback: Callable[[dict[str, Any]], None] | None) -> None:
        self._on_update = callback

    def is_busy(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def refresh(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        self._emit(snapshot)
        return snapshot

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            generated = self._scan_images()
            artifacts = self._scan_artifacts()
            configs = self._scan_dataset_configs()
            capabilities = self._discover_capabilities()
            return {
                "busy": self.is_busy(),
                "job_kind": self._job_kind,
                "job_title": self._job_title,
                "scripts_root": str(self.scripts_root),
                "python_exe": str(self.python_exe),
                "accelerate_exe": str(self.accelerate_exe),
                "generated_root": str(self.generated_root),
                "training_root": str(self.training_root),
                "configs_root": str(self.configs_root),
                "generated_images": generated,
                "training_artifacts": artifacts,
                "dataset_configs": configs,
                "latest_preview": generated[0] if generated else "",
                "latest_artifact": artifacts[0] if artifacts else "",
                "last_dataset_config": self._last_dataset_config,
                "capabilities": capabilities,
                "recent_runs": [record.__dict__ for record in self._recent_runs[:10]],
                "logs": "\n".join(self._log_lines[-300:]),
            }

    def start_generation(self, config: dict[str, Any]) -> dict[str, Any]:
        self._ensure_idle()
        script_path = self.scripts_root / "gen_img.py"
        if not script_path.exists():
            raise FileNotFoundError(f"Missing generation script: {script_path}")

        workflow = self._normalize_workflow(config.get("workflow"))
        ckpt = str(Path(str(config["model_path"])).expanduser())
        outdir = Path(str(config.get("output_dir") or self.generated_root)).expanduser()
        outdir.mkdir(parents=True, exist_ok=True)
        prompt = str(config.get("prompt", "")).strip()
        if not prompt:
            raise ValueError("Prompt is required for image generation.")

        width, height = self._parse_resolution_pair(config.get("width", 1024), config.get("height", 1024))
        precision = str(config.get("precision", "fp16")).strip().lower() or "fp16"
        attention = str(config.get("attention", "xformers")).strip().lower() or "xformers"

        command = [
            str(self.python_exe),
            str(script_path),
            "--ckpt",
            ckpt,
            "--outdir",
            str(outdir),
            "--prompt",
            prompt,
            "--W",
            str(width),
            "--H",
            str(height),
            "--steps",
            str(self._parse_int(config.get("steps", 28), minimum=1)),
            "--scale",
            str(self._parse_float(config.get("guidance_scale", 7.5), minimum=0.0)),
            "--sampler",
            str(config.get("sampler", "euler_a") or "euler_a"),
            "--images_per_prompt",
            str(self._parse_int(config.get("images_per_prompt", 1), minimum=1)),
        ]

        if workflow == "sdxl":
            command.append("--sdxl")
        elif self._as_bool(config.get("use_v2", False)):
            command.append("--v2")
        if self._as_bool(config.get("v_parameterization", False)):
            command.append("--v_parameterization")

        self._apply_attention_backend(command, attention)
        self._apply_generation_precision(command, precision)

        batch_size = self._parse_int(config.get("batch_size", 1), minimum=1)
        if batch_size > 1:
            command.extend(["--batch_size", str(batch_size)])

        clip_skip = self._clean(config.get("clip_skip"))
        if clip_skip:
            command.extend(["--clip_skip", clip_skip])

        vae_path = self._clean(config.get("vae_path"))
        if vae_path:
            command.extend(["--vae", str(Path(vae_path).expanduser())])

        negative_prompt = self._clean(config.get("negative_prompt"))
        if negative_prompt:
            command.extend(["--negative_prompt", negative_prompt])

        seed = self._clean(config.get("seed"))
        if seed:
            command.extend(["--seed", seed])

        lora_weights = self._list_values(config.get("lora_weights"))
        if lora_weights:
            command.extend(["--network_module", *["networks.lora" for _ in lora_weights]])
            command.extend(["--network_weights", *lora_weights])
            lora_muls = self._list_values(config.get("lora_multipliers"))
            if lora_muls:
                if len(lora_muls) == 1 and len(lora_weights) > 1:
                    lora_muls = lora_muls * len(lora_weights)
                if len(lora_muls) == len(lora_weights):
                    command.extend(["--network_mul", *lora_muls])

        title = f"Generate images - {workflow.upper()} - {Path(ckpt).name}"
        self._launch_job("generation", title, command, outdir)
        return self.snapshot()

    def start_training(self, config: dict[str, Any]) -> dict[str, Any]:
        self._ensure_idle()
        train_type = self._normalize_training_type(config.get("train_type"))
        workflow = self._normalize_workflow(config.get("workflow"))
        script_path = self._resolve_training_script(train_type, workflow)
        if not script_path.exists():
            raise FileNotFoundError(f"Missing training script: {script_path}")

        model_path = self._clean(config.get("model_path"))
        if not model_path:
            raise ValueError("Model path is required for training.")

        output_dir = Path(str(config.get("output_dir") or self.training_root)).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_name = self._clean(config.get("output_name")) or "astrea_training_run"

        base_args = [
            str(script_path),
            "--pretrained_model_name_or_path",
            str(Path(model_path).expanduser()),
            "--output_dir",
            str(output_dir),
            "--output_name",
            output_name,
        ]

        self._append_training_dataset_args(base_args, config, train_type=train_type)
        self._append_training_common_args(base_args, config, train_type=train_type, workflow=workflow)
        self._append_training_specific_args(base_args, config, train_type=train_type, workflow=workflow)
        self._append_extra_args(base_args, config.get("extra_args"))

        command = self._wrap_training_command(base_args)
        label = {
            "dreambooth": "DreamBooth",
            "lora": "LoRA",
            "embedding": "Embedding",
            "finetuning": "Finetuning",
        }[train_type]
        title = f"Train {label} - {workflow.upper()} - {output_name}"
        self._launch_job("training", title, command, output_dir)
        return self.snapshot()

    def start_captioning(self, config: dict[str, Any]) -> dict[str, Any]:
        self._ensure_idle()
        caption_mode = self._normalize_caption_mode(config.get("caption_mode"))
        script_path = self._resolve_caption_script(caption_mode)
        if not script_path.exists():
            raise FileNotFoundError(f"Missing caption script: {script_path}")

        image_dir = self._clean(config.get("image_dir"))
        if not image_dir:
            raise ValueError("Image directory is required for captioning.")

        command = [str(self.python_exe), str(script_path), str(Path(image_dir).expanduser())]

        self._append_value(command, "--caption_extension", config.get("caption_extension"))
        self._append_value(command, "--batch_size", config.get("batch_size"))
        self._append_value(command, "--max_data_loader_n_workers", config.get("max_data_loader_n_workers"))
        self._append_flag(command, "--recursive", config.get("recursive"))

        if caption_mode == "blip":
            self._append_value(command, "--caption_weights", config.get("caption_weights"))
            self._append_flag(command, "--beam_search", config.get("beam_search"))
            self._append_value(command, "--num_beams", config.get("num_beams"))
            self._append_value(command, "--top_p", config.get("top_p"))
            self._append_value(command, "--max_length", config.get("max_length"))
            self._append_value(command, "--min_length", config.get("min_length"))
            self._append_value(command, "--seed", config.get("seed"))
            title = f"Caption dataset - BLIP - {Path(image_dir).name}"
            output_target = Path(image_dir).expanduser()
        else:
            self._append_value(command, "--repo_id", config.get("repo_id"))
            self._append_value(command, "--model_dir", config.get("model_dir"))
            self._append_value(command, "--output_path", config.get("output_path"))
            self._append_value(command, "--thresh", config.get("thresh"))
            self._append_value(command, "--general_threshold", config.get("general_threshold"))
            self._append_value(command, "--character_threshold", config.get("character_threshold"))
            self._append_flag(command, "--force_download", config.get("force_download"))
            self._append_flag(command, "--remove_underscore", config.get("remove_underscore"))
            self._append_flag(command, "--append_tags", config.get("append_tags"))
            self._append_flag(command, "--use_rating_tags", config.get("use_rating_tags"))
            self._append_flag(command, "--use_quality_tags", config.get("use_quality_tags"))
            self._append_flag(command, "--character_tags_first", config.get("character_tags_first"))
            self._append_flag(command, "--frequency_tags", config.get("frequency_tags"))
            self._append_flag(command, "--onnx", config.get("onnx"))
            self._append_value(command, "--always_first_tags", config.get("always_first_tags"))
            self._append_value(command, "--undesired_tags", config.get("undesired_tags"))
            self._append_value(command, "--caption_separator", config.get("caption_separator"))
            self._append_value(command, "--tag_replacement", config.get("tag_replacement"))
            title = f"Tag dataset - WD14 - {Path(image_dir).name}"
            output_target = Path(self._clean(config.get("output_path")) or image_dir).expanduser()

        self._append_extra_args(command, config.get("extra_args"))
        self._launch_job("captioning", title, command, output_target)
        return self.snapshot()

    def build_dataset_config(self, config: dict[str, Any]) -> dict[str, Any]:
        path = self._write_dataset_config(config)
        self._record_run("dataset_config", f"Build dataset config - {Path(path).name}", path, "completed")
        self._append_log(f"Dataset config written: {path}")
        snapshot = self.snapshot()
        self._emit(snapshot)
        return snapshot

    def cancel_current_job(self) -> dict[str, Any]:
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            self._append_log("Job cancellation requested.")
        return self.refresh()

    def _ensure_idle(self) -> None:
        if self.is_busy():
            raise RuntimeError("Astrea is already running a job.")

    def _launch_job(self, kind: JobKind, title: str, command: list[str], output_path: Path) -> None:
        env = self._build_env()
        self._append_log(f"$ {' '.join(command)}")
        process = subprocess.Popen(
            command,
            cwd=str(self.scripts_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        with self._lock:
            self._process = process
            self._job_kind = kind
            self._job_title = title
        thread = threading.Thread(target=self._drain_process, args=(process, kind, title, output_path), daemon=True)
        thread.start()
        self._emit(self.snapshot())

    def _drain_process(self, process: subprocess.Popen[str], kind: JobKind, title: str, output_path: Path) -> None:
        if process.stdout is not None:
            for line in process.stdout:
                self._append_log(line.rstrip())
        exit_code = process.wait()
        status = "completed" if exit_code == 0 else f"failed ({exit_code})"
        self._record_run(kind, title, str(output_path), status)
        with self._lock:
            self._process = None
            self._job_kind = None
            self._job_title = None
        self._append_log(f"{title}: {status}")
        self._emit(self.snapshot())

    def _record_run(self, kind: JobKind, title: str, output_path: str, status: str) -> None:
        with self._lock:
            self._recent_runs.insert(0, AstreaRunRecord(kind=kind, title=title, output_path=output_path, status=status))
            del self._recent_runs[14:]

    def _scan_images(self) -> list[str]:
        return self._scan_files(self.generated_root, {".png", ".jpg", ".jpeg", ".webp"}, limit=24)

    def _scan_artifacts(self) -> list[str]:
        return self._scan_files(self.training_root, {".safetensors", ".ckpt", ".pt", ".json", ".txt"}, limit=24)

    def _scan_dataset_configs(self) -> list[str]:
        return self._scan_files(self.configs_root, {".toml", ".json"}, limit=24)

    def _scan_files(self, root: Path, exts: set[str], *, limit: int) -> list[str]:
        if not root.exists():
            return []
        files = [
            str(path)
            for path in sorted(
                root.rglob("*"),
                key=lambda item: item.stat().st_mtime if item.exists() else 0,
                reverse=True,
            )
            if path.is_file() and path.suffix.lower() in exts
        ]
        return files[:limit]

    def _discover_capabilities(self) -> dict[str, Any]:
        scripts = {
            "gen_img": self.scripts_root / "gen_img.py",
            "train_network": self.scripts_root / "train_network.py",
            "sdxl_train_network": self.scripts_root / "sdxl_train_network.py",
            "train_db": self.scripts_root / "train_db.py",
            "fine_tune": self.scripts_root / "fine_tune.py",
            "train_textual_inversion": self.scripts_root / "train_textual_inversion.py",
            "sdxl_train_textual_inversion": self.scripts_root / "sdxl_train_textual_inversion.py",
            "make_captions": self.scripts_root / "finetune" / "make_captions.py",
            "wd14_tagger": self.scripts_root / "finetune" / "tag_images_by_wd14_tagger.py",
        }
        available_scripts = {name: path.exists() for name, path in scripts.items()}
        workflows: list[dict[str, str]] = [{"value": "base", "label": "SD 1.x / 2.x"}]
        if available_scripts["sdxl_train_network"]:
            workflows.append({"value": "sdxl", "label": "SDXL"})
        return {
            "scripts": [{"name": name, "path": str(path), "available": available_scripts[name]} for name, path in scripts.items()],
            "generate_workflows": workflows,
            "train_workflows": workflows,
            "train_modes": [
                {"value": "dreambooth", "label": "DreamBooth"},
                {"value": "lora", "label": "LoRA"},
                {"value": "embedding", "label": "Embedding"},
                {"value": "finetuning", "label": "Finetuning"},
            ],
            "caption_modes": [
                {"value": "blip", "label": "BLIP"},
                {"value": "wd14", "label": "WD14 Tagger"},
            ],
            "attention_backends": ["xformers", "sdpa", "none"],
            "precisions": ["fp16", "bf16", "fp32"],
            "has_accelerate": self.accelerate_exe.exists(),
        }

    def _write_dataset_config(self, config: dict[str, Any]) -> str:
        image_dir = self._clean(config.get("image_dir"))
        if not image_dir:
            raise ValueError("Dataset image directory is required.")

        name = self._slug(self._clean(config.get("name")) or "astrea_dataset")
        output_path = self._clean(config.get("output_path"))
        target = Path(output_path).expanduser() if output_path else self.configs_root / f"{name}.toml"
        target.parent.mkdir(parents=True, exist_ok=True)

        width, height = self._parse_resolution_text(str(config.get("resolution", "1024,1024")))
        batch_size = self._parse_int(config.get("batch_size", 1), minimum=1)
        num_repeats = self._parse_int(config.get("num_repeats", 10), minimum=1)
        keep_tokens = self._parse_int(config.get("keep_tokens", 1), minimum=0)
        min_bucket = self._parse_int(config.get("min_bucket_reso", 256), minimum=64)
        max_bucket = self._parse_int(config.get("max_bucket_reso", max(width, height)), minimum=64)

        shuffle_caption = self._as_bool(config.get("shuffle_caption", True))
        enable_bucket = self._as_bool(config.get("enable_bucket", True))
        bucket_no_upscale = self._as_bool(config.get("bucket_no_upscale", True))
        caption_extension = self._clean(config.get("caption_extension")) or ".txt"
        class_tokens = self._clean(config.get("class_tokens"))
        caption_prefix = self._clean(config.get("caption_prefix"))
        caption_suffix = self._clean(config.get("caption_suffix"))

        lines = [
            "[general]",
            f"shuffle_caption = {'true' if shuffle_caption else 'false'}",
            f'caption_extension = "{caption_extension}"',
            f"keep_tokens = {keep_tokens}",
            "",
            "[[datasets]]",
            f"resolution = [{width}, {height}]",
            f"batch_size = {batch_size}",
            f"enable_bucket = {'true' if enable_bucket else 'false'}",
            f"bucket_no_upscale = {'true' if bucket_no_upscale else 'false'}",
            f"min_bucket_reso = {min_bucket}",
            f"max_bucket_reso = {max_bucket}",
            "",
            "  [[datasets.subsets]]",
            f'  image_dir = "{image_dir}"',
            f"  num_repeats = {num_repeats}",
        ]
        if class_tokens:
            lines.append(f'  class_tokens = "{class_tokens}"')
        if caption_prefix:
            lines.append(f'  caption_prefix = "{caption_prefix}"')
        if caption_suffix:
            lines.append(f'  caption_suffix = "{caption_suffix}"')

        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._last_dataset_config = str(target)
        return str(target)

    def _build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def _append_log(self, line: str) -> None:
        with self._lock:
            self._log_lines.append(line)
            del self._log_lines[:-600]

    def _emit(self, payload: dict[str, Any]) -> None:
        callback = self._on_update
        if callback is not None:
            callback(payload)

    def _resolve_training_script(self, train_type: TrainingKind, workflow: WorkflowKind) -> Path:
        if train_type == "dreambooth":
            return self.scripts_root / ("sdxl_train.py" if workflow == "sdxl" else "train_db.py")
        if train_type == "embedding":
            return self.scripts_root / ("sdxl_train_textual_inversion.py" if workflow == "sdxl" else "train_textual_inversion.py")
        if train_type == "finetuning":
            return self.scripts_root / ("sdxl_train.py" if workflow == "sdxl" else "fine_tune.py")
        return self.scripts_root / ("sdxl_train_network.py" if workflow == "sdxl" else "train_network.py")

    def _resolve_caption_script(self, caption_mode: CaptionMode) -> Path:
        if caption_mode == "wd14":
            return self.scripts_root / "finetune" / "tag_images_by_wd14_tagger.py"
        return self.scripts_root / "finetune" / "make_captions.py"

    def _append_training_dataset_args(self, args: list[str], config: dict[str, Any], *, train_type: TrainingKind) -> None:
        dataset_config = self._clean(config.get("dataset_config"))
        train_data_dir = self._clean(config.get("train_data_dir"))
        if dataset_config:
            args.extend(["--dataset_config", str(Path(dataset_config).expanduser())])
        else:
            if not train_data_dir:
                raise ValueError("Provide either a dataset config or a train data directory.")
            args.extend(["--train_data_dir", str(Path(train_data_dir).expanduser())])
            if train_type == "dreambooth":
                self._append_value(args, "--reg_data_dir", self._clean(config.get("reg_data_dir")))
            self._append_value(args, "--in_json", self._clean(config.get("metadata_json")))

        self._append_value(args, "--caption_extension", config.get("caption_extension"))
        self._append_value(args, "--caption_separator", config.get("caption_separator"))
        self._append_value(args, "--dataset_repeats", config.get("dataset_repeats"))
        self._append_value(args, "--keep_tokens", config.get("keep_tokens"))
        self._append_value(args, "--caption_prefix", config.get("caption_prefix"))
        self._append_value(args, "--caption_suffix", config.get("caption_suffix"))
        self._append_flag(args, "--shuffle_caption", config.get("shuffle_caption"))
        self._append_flag(args, "--enable_bucket", config.get("enable_bucket"))
        self._append_flag(args, "--bucket_no_upscale", config.get("bucket_no_upscale"))
        self._append_value(args, "--min_bucket_reso", config.get("min_bucket_reso"))
        self._append_value(args, "--max_bucket_reso", config.get("max_bucket_reso"))
        self._append_value(args, "--bucket_reso_steps", config.get("bucket_reso_steps"))
        self._append_flag(args, "--color_aug", config.get("color_aug"))
        self._append_flag(args, "--flip_aug", config.get("flip_aug"))
        self._append_flag(args, "--random_crop", config.get("random_crop"))

    def _append_training_common_args(
        self,
        args: list[str],
        config: dict[str, Any],
        *,
        train_type: TrainingKind,
        workflow: WorkflowKind,
    ) -> None:
        precision = self._normalize_precision(config.get("precision"))
        mixed_precision = precision if precision in {"fp16", "bf16"} else "no"
        save_precision = "float" if precision == "fp32" else precision
        attention = self._clean(config.get("attention")).lower() or ("sdpa" if workflow == "sdxl" else "xformers")

        self._append_value(args, "--resolution", config.get("resolution"))
        self._append_value(args, "--train_batch_size", config.get("train_batch_size"))
        self._append_value(args, "--max_train_epochs", config.get("epochs"))
        self._append_value(args, "--max_train_steps", config.get("max_train_steps"))
        self._append_value(args, "--gradient_accumulation_steps", config.get("gradient_accumulation_steps"))
        self._append_value(args, "--learning_rate", config.get("learning_rate"))
        self._append_value(args, "--optimizer_type", config.get("optimizer_type"))

        optimizer_args = self._shell_words(config.get("optimizer_args"))
        if optimizer_args:
            args.extend(["--optimizer_args", *optimizer_args])

        self._append_value(args, "--lr_scheduler", config.get("lr_scheduler"))
        self._append_value(args, "--lr_warmup_steps", config.get("lr_warmup_steps"))
        self._append_value(args, "--lr_scheduler_num_cycles", config.get("lr_scheduler_num_cycles"))
        self._append_value(args, "--max_grad_norm", config.get("max_grad_norm"))
        self._append_value(args, "--save_every_n_epochs", config.get("save_every_n_epochs"))
        self._append_value(args, "--save_every_n_steps", config.get("save_every_n_steps"))
        self._append_value(args, "--seed", config.get("seed"))
        self._append_value(args, "--clip_skip", config.get("clip_skip"))
        self._append_value(args, "--vae", config.get("vae_path"))
        self._append_value(args, "--mixed_precision", mixed_precision)
        self._append_value(args, "--save_precision", save_precision)
        self._append_value(args, "--save_model_as", self._normalize_save_format(config.get("save_model_as"), train_type))
        self._append_value(args, "--training_comment", config.get("training_comment"))
        self._append_value(args, "--logging_dir", config.get("logging_dir"))
        self._append_value(args, "--log_with", config.get("log_with"))
        self._append_value(args, "--validation_split", config.get("validation_split"))
        self._append_value(args, "--validate_every_n_steps", config.get("validate_every_n_steps"))
        self._append_value(args, "--validate_every_n_epochs", config.get("validate_every_n_epochs"))
        self._append_value(args, "--max_validation_steps", config.get("max_validation_steps"))

        self._append_flag(args, "--gradient_checkpointing", config.get("gradient_checkpointing"))
        self._append_flag(args, "--cache_latents", config.get("cache_latents"))
        self._append_flag(args, "--cache_latents_to_disk", config.get("cache_latents_to_disk"))
        if workflow == "sdxl":
            self._append_flag(args, "--cache_text_encoder_outputs", config.get("cache_text_encoder_outputs"))
        self._append_flag(args, "--no_half_vae", config.get("no_half_vae"))

        if workflow == "base":
            self._append_flag(args, "--v2", config.get("v2"))
            self._append_flag(args, "--v_parameterization", config.get("v_parameterization"))

        if train_type == "dreambooth":
            self._append_value(args, "--prior_loss_weight", config.get("prior_loss_weight"))
            if workflow == "base":
                self._append_value(args, "--stop_text_encoder_training", config.get("stop_text_encoder_training"))
                self._append_flag(args, "--no_token_padding", config.get("no_token_padding"))

        if train_type == "lora":
            self._append_flag(args, "--cpu_offload_checkpointing", config.get("cpu_offload_checkpointing"))

        self._apply_attention_backend(args, attention)

    def _append_training_specific_args(
        self,
        args: list[str],
        config: dict[str, Any],
        *,
        train_type: TrainingKind,
        workflow: WorkflowKind,
    ) -> None:
        if train_type == "lora":
            self._append_value(args, "--network_module", self._clean(config.get("network_module")) or "networks.lora")
            self._append_value(args, "--network_dim", config.get("network_dim"))
            self._append_value(args, "--network_alpha", config.get("network_alpha"))
            self._append_value(args, "--network_dropout", config.get("network_dropout"))
            self._append_value(args, "--network_weights", config.get("network_weights"))

            network_args = self._shell_words(config.get("network_args"))
            if network_args:
                args.extend(["--network_args", *network_args])

            base_weights = self._list_values(config.get("base_weights"))
            if base_weights:
                args.extend(["--base_weights", *base_weights])
            base_weight_muls = self._list_values(config.get("base_weights_multiplier"))
            if base_weight_muls:
                args.extend(["--base_weights_multiplier", *base_weight_muls])

            self._append_flag(args, "--network_train_unet_only", config.get("network_train_unet_only"))
            self._append_flag(args, "--network_train_text_encoder_only", config.get("network_train_text_encoder_only"))
            self._append_value(args, "--unet_lr", config.get("unet_lr"))

            text_encoder_lrs = self._collect_text_encoder_lrs(config, workflow=workflow)
            if text_encoder_lrs:
                args.extend(["--text_encoder_lr", *text_encoder_lrs])
            return

        if train_type == "embedding":
            token_string = self._clean(config.get("token_string"))
            if not token_string:
                raise ValueError("Token string is required for embedding training.")
            args.extend(["--token_string", token_string])
            self._append_value(args, "--weights", config.get("weights"))
            self._append_value(args, "--init_word", config.get("init_word"))
            self._append_value(args, "--num_vectors_per_token", config.get("num_vectors_per_token"))
            self._append_flag(args, "--use_object_template", config.get("use_object_template"))
            self._append_flag(args, "--use_style_template", config.get("use_style_template"))
            return

        if workflow == "sdxl":
            self._append_flag(args, "--train_text_encoder", config.get("train_text_encoder"))
            self._append_value(args, "--learning_rate_te1", config.get("learning_rate_te1"))
            self._append_value(args, "--learning_rate_te2", config.get("learning_rate_te2"))
        else:
            self._append_flag(args, "--train_text_encoder", config.get("train_text_encoder"))
            self._append_value(args, "--learning_rate_te", config.get("learning_rate_te"))

    def _wrap_training_command(self, script_args: list[str]) -> list[str]:
        if self.accelerate_exe.exists():
            return [str(self.accelerate_exe), "launch", "--num_cpu_threads_per_process", "1", *script_args]
        return [str(self.python_exe), *script_args]

    def _collect_text_encoder_lrs(self, config: dict[str, Any], *, workflow: WorkflowKind) -> list[str]:
        if workflow == "sdxl":
            lr1 = self._clean(config.get("text_encoder_lr1"))
            lr2 = self._clean(config.get("text_encoder_lr2"))
            if lr1 or lr2:
                values: list[str] = []
                if lr1:
                    values.append(lr1)
                if lr2:
                    values.append(lr2)
                return values
        text_encoder_lr = self._clean(config.get("text_encoder_lr"))
        return [text_encoder_lr] if text_encoder_lr else []

    def _append_value(self, args: list[str], flag: str, value: Any) -> None:
        raw = self._clean(value)
        if raw:
            args.extend([flag, raw])

    def _append_flag(self, args: list[str], flag: str, value: Any) -> None:
        if self._as_bool(value):
            args.append(flag)

    def _append_extra_args(self, args: list[str], value: Any) -> None:
        args.extend(self._shell_words(value))

    def _shell_words(self, value: Any) -> list[str]:
        raw = self._clean(value)
        if not raw:
            return []
        try:
            return shlex.split(raw, posix=os.name != "nt")
        except ValueError as exc:
            raise ValueError(f"Invalid CLI fragments: {exc}") from exc

    def _normalize_precision(self, value: Any) -> str:
        raw = self._clean(value).lower()
        return raw if raw in {"fp16", "bf16", "fp32"} else "fp16"

    def _normalize_save_format(self, value: Any, train_type: TrainingKind) -> str:
        raw = self._clean(value).lower()
        if train_type in {"dreambooth", "finetuning"}:
            valid = {"ckpt", "safetensors", "diffusers", "diffusers_safetensors"}
            return raw if raw in valid else "safetensors"
        if train_type == "embedding":
            valid = {"ckpt", "pt", "safetensors"}
            return raw if raw in valid else "pt"
        valid = {"ckpt", "pt", "safetensors"}
        return raw if raw in valid else "safetensors"

    def _clean(self, value: Any) -> str:
        return str(value or "").strip()

    def _list_values(self, value: Any) -> list[str]:
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        raw = self._clean(value)
        if not raw:
            return []
        items: list[str] = []
        for chunk in raw.replace(";", "\n").splitlines():
            for part in chunk.split(","):
                cleaned = part.strip()
                if cleaned:
                    items.append(cleaned)
        return items

    def _normalize_workflow(self, value: Any) -> WorkflowKind:
        raw = str(value or "base").strip().lower()
        return "sdxl" if raw == "sdxl" else "base"

    def _normalize_training_type(self, value: Any) -> TrainingKind:
        raw = self._clean(value).lower()
        if raw in {"dreambooth", "embedding", "finetuning"}:
            return raw  # type: ignore[return-value]
        return "lora"

    def _normalize_caption_mode(self, value: Any) -> CaptionMode:
        raw = self._clean(value).lower()
        return "wd14" if raw == "wd14" else "blip"

    def _apply_attention_backend(self, args: list[str], backend: str) -> None:
        normalized = backend.strip().lower()
        if normalized == "xformers":
            args.append("--xformers")
        elif normalized == "sdpa":
            args.append("--sdpa")

    def _apply_generation_precision(self, args: list[str], precision: str) -> None:
        normalized = precision.strip().lower()
        if normalized == "fp16":
            args.append("--fp16")
        elif normalized == "bf16":
            args.append("--bf16")

    def _parse_int(self, value: Any, *, minimum: int | None = None) -> int:
        parsed = int(float(str(value).strip()))
        if minimum is not None and parsed < minimum:
            raise ValueError(f"Expected integer >= {minimum}, got {parsed}.")
        return parsed

    def _parse_float(self, value: Any, *, minimum: float | None = None) -> float:
        parsed = float(str(value).strip())
        if minimum is not None and parsed < minimum:
            raise ValueError(f"Expected float >= {minimum}, got {parsed}.")
        return parsed

    def _parse_resolution_pair(self, width: Any, height: Any) -> tuple[int, int]:
        return (self._parse_int(width, minimum=64), self._parse_int(height, minimum=64))

    def _parse_resolution_text(self, value: str) -> tuple[int, int]:
        raw = value.strip().replace("x", ",").replace(" ", "")
        if "," not in raw:
            size = self._parse_int(raw, minimum=64)
            return size, size
        left, right = raw.split(",", 1)
        return self._parse_resolution_pair(left, right)

    def _as_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _slug(self, value: str) -> str:
        cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")
        return cleaned.strip("_") or "astrea_dataset"
