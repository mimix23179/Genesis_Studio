from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import threading
import time
from pathlib import Path

import butterflyui as ui


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = REPO_ROOT / "env" / "Scripts" / "python.exe"
TRAIN_SCRIPT = REPO_ROOT / "scripts" / "sakura" / "run_full_training.py"


class TrainerShell:
    _BG = "#0B0F10"
    _SURFACE = "#11181C"
    _BORDER = "#1E2A30"
    _TEXT = "#C8FFD8"
    _MUTED = "#7FBF8E"
    _ACCENT = "#39FF14"

    def __init__(self, page: ui.Page) -> None:
        self.page = page
        self._ui_loop: asyncio.AbstractEventLoop | None = None
        self._running = False
        self._proc: subprocess.Popen[str] | None = None
        self._log_lines: list[str] = []
        self._test_stream = ""

        self.title = ui.Text(
            "Sakura Trainer",
            font_size=22,
            font_weight="700",
            color=self._TEXT,
        )
        self.subtitle = ui.Text(
            "Live training monitor with progress + streaming sanity tests",
            font_size=12,
            color=self._MUTED,
        )

        self.progress_text = ui.Text(
            "Overall Progress: 0%",
            font_size=14,
            font_weight="600",
            color=self._TEXT,
        )
        self.progress_bar_text = ui.Text(
            "[--------------------------------] 0%",
            font_size=12,
            color=self._MUTED,
        )
        self.status_text = ui.Text(
            "Idle",
            font_size=12,
            color=self._MUTED,
        )

        self.steps_input = ui.TextField(
            label="Steps",
            value="1000",
            events=["change"],
            width=120,
            bgcolor="#000000",
            text_color="#39FF14",
            border_color="#39FF14",
            font_family="monospace",
            label_color="#7FBF8E",
        )
        self.batch_input = ui.TextField(
            label="Batch",
            value="16",
            events=["change"],
            width=120,
            bgcolor="#000000",
            text_color="#39FF14",
            border_color="#39FF14",
            font_family="monospace",
            label_color="#7FBF8E",
        )
        self.block_input = ui.TextField(
            label="Block",
            value="256",
            events=["change"],
            width=120,
            bgcolor="#000000",
            text_color="#39FF14",
            border_color="#39FF14",
            font_family="monospace",
            label_color="#7FBF8E",
        )

        self.start_button = ui.Button(
            text="Start Training",
            variant="filled",
            events=["click"],
            style={
                "background": "#39FF14",
                "color": "#06110A",
                "font_weight": "600",
                "border_radius": "10",
            },
        )
        self.stop_button = ui.Button(
            text="Stop",
            variant="outlined",
            events=["click"],
            style={
                "border_radius": "10",
                "font_weight": "600",
                "border_color": "#39FF14",
                "color": "#39FF14",
            },
        )

        self.log_text = ui.Text(
            "Ready. Click Start Training to run scripts/sakura/run_full_training.py",
            font_size=12,
            font_family="monospace",
            color=self._TEXT,
        )

        self.test_title = ui.Text(
            "Streaming Test",
            font_size=18,
            font_weight="700",
            color="#FFFFFF",
        )
        self.test_status = ui.Text(
            "Waiting…",
            font_size=12,
            color="#D1D5DB",
        )
        self.test_stream_text = ui.Text(
            "",
            font_size=13,
            color="#FFFFFF",
        )

        self.test_overlay = ui.Container(
            ui.Surface(
                ui.Column(
                    self.test_title,
                    self.test_status,
                    ui.Divider(color="#334155"),
                    self.test_stream_text,
                    spacing=8,
                ),
                padding="16",
                bgcolor="#000000",
                border_color="#39FF14",
                border_width="1",
                radius="14",
            ),
            visible=False,
            padding="12",
        )

    def mount(self) -> None:
        self.page.title = "Genesis Sakura Trainer"
        try:
            self._ui_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._ui_loop = None

        self.page.root = self._build_root()
        session = self.page.session
        self.start_button.on_click(session, self._on_start)
        self.stop_button.on_click(session, self._on_stop)
        self._request_ui_refresh()

    def _build_root(self):
        header = ui.Surface(
            ui.Column(self.title, self.subtitle, spacing=4),
            padding="16",
            bgcolor=self._SURFACE,
            border_color=self._BORDER,
            border_width="1",
            radius="14",
        )

        controls = ui.Surface(
            ui.Row(
                self.steps_input,
                self.batch_input,
                self.block_input,
                ui.Spacer(),
                self.start_button,
                self.stop_button,
                spacing=10,
            ),
            padding="12",
            bgcolor=self._SURFACE,
            border_color=self._BORDER,
            border_width="1",
            radius="14",
        )

        progress_card = ui.Surface(
            ui.Column(self.progress_text, self.progress_bar_text, self.status_text, spacing=6),
            padding="12",
            bgcolor=self._SURFACE,
            border_color=self._BORDER,
            border_width="1",
            radius="14",
        )

        logs = ui.Surface(
            ui.ScrollableColumn(self.log_text, padding={"left": 6, "right": 6, "top": 6, "bottom": 6}),
            padding="8",
            bgcolor="#000000",
            border_color="#39FF14",
            border_width="1",
            radius="14",
            expand=True,
        )

        return ui.Container(
            ui.Column(
                ui.Container(header, padding={"left": 12, "right": 12, "top": 12, "bottom": 6}),
                ui.Container(controls, padding={"left": 12, "right": 12, "top": 6, "bottom": 6}),
                ui.Container(progress_card, padding={"left": 12, "right": 12, "top": 6, "bottom": 6}),
                ui.Container(self.test_overlay, padding={"left": 12, "right": 12, "top": 0, "bottom": 6}),
                ui.Container(logs, padding={"left": 12, "right": 12, "top": 6, "bottom": 12}, expand=True),
                expand=True,
                spacing=0,
            ),
            expand=True,
            bgcolor=self._BG,
        )

    def _on_start(self, event=None) -> None:
        if self._running:
            return
        self._running = True
        self._append_log("Starting full training pipeline…")
        self._set_status("Running: bootstrapping")
        threading.Thread(target=self._run_training, daemon=True).start()

    def _on_stop(self, event=None) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            self._append_log("Stop requested. Terminating process…")
            self._set_status("Stopping")

    def _run_training(self) -> None:
        steps = self._safe_int(self.steps_input, 1000)
        batch = self._safe_int(self.batch_input, 16)
        block = self._safe_int(self.block_input, 256)

        cmd = [
            str(PYTHON),
            str(TRAIN_SCRIPT),
            "--json-progress",
            "--clean",
            "--steps",
            str(steps),
            "--batch-size",
            str(batch),
            "--block-size",
            str(block),
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self._proc = proc
            assert proc.stdout is not None

            for raw_line in proc.stdout:
                line = raw_line.rstrip("\n")
                if not line.strip():
                    continue
                self._handle_output_line(line)

            code = proc.wait()
            if code == 0:
                self._run_on_ui(self._set_status, "Completed")
                self._run_on_ui(self._append_log, "Training completed successfully.")
                self._run_on_ui(self._update_progress, 100)
            else:
                self._run_on_ui(self._set_status, f"Failed (exit {code})")
                self._run_on_ui(self._append_log, f"Training failed with exit code {code}.")
        except Exception as exc:
            self._run_on_ui(self._set_status, "Failed")
            self._run_on_ui(self._append_log, f"Trainer error: {exc}")
        finally:
            self._proc = None
            self._running = False
            self._run_on_ui(self._request_ui_refresh)

    def _handle_output_line(self, line: str) -> None:
        text = line.strip()
        if text.startswith("{"):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                self._run_on_ui(self._append_log, line)
                return

            # Debug: log receipt of JSON events for troubleshooting
            self._run_on_ui(self._append_log, f"[json] received: {payload.get('event','(no-event)')}")

            event_name = str(payload.get("event", ""))
            if event_name == "pipeline.progress":
                pct = int(payload.get("percent", 0))
                self._run_on_ui(self._update_progress, pct)
                current = str(payload.get("current", ""))
                if current:
                    self._run_on_ui(self._set_status, f"Running: {current}")
                return
            if event_name == "pipeline.clean":
                removed = int(payload.get("removed", 0))
                self._run_on_ui(self._append_log, f"[clean] removed {removed} previous artifact(s)")
                self._run_on_ui(self._set_status, "Running: cleaned previous artifacts")
                return
            if event_name == "train.heartbeat":
                step = int(payload.get("step", 0))
                steps = int(payload.get("steps", 0))
                loss = payload.get("loss")
                if isinstance(loss, (int, float)):
                    self._run_on_ui(self._set_status, f"Running: train_sakura step {step}/{steps} · loss {float(loss):.4f}")
                else:
                    self._run_on_ui(self._set_status, f"Running: train_sakura step {step}/{steps}")
                return
            if event_name == "train.progress":
                return
            if event_name == "train.test.start":
                pct = int(payload.get("percent", 0))
                message = str(payload.get("message", "Running streaming test"))
                self._run_on_ui(self._show_test_overlay, pct, message)
                return
            if event_name == "train.test.stream":
                chunk = str(payload.get("chunk", ""))
                self._run_on_ui(self._append_test_stream, chunk)
                return
            if event_name == "train.test.end":
                passed = bool(payload.get("passed", False))
                pct = int(payload.get("percent", 0))
                self._run_on_ui(self._finish_test_overlay, pct, passed)
                return

            return

        self._run_on_ui(self._append_log, line)

    def _show_test_overlay(self, percent: int, message: str) -> None:
        self._test_stream = ""
        self.test_status.patch(text=f"{message} ({percent}%)")
        self.test_stream_text.patch(text="")
        self.test_overlay.patch(visible=True)
        self._append_log(f"[test] started at {percent}%")
        self._request_ui_refresh()

    def _append_test_stream(self, chunk: str) -> None:
        self._test_stream += chunk
        self.test_stream_text.patch(text=self._test_stream)
        self._request_ui_refresh()

    def _finish_test_overlay(self, percent: int, passed: bool) -> None:
        status = "passed" if passed else "failed"
        self.test_status.patch(text=f"Sanity test {status} at {percent}% — fading out…")
        self._append_log(f"[test] {status} at {percent}%")
        self._request_ui_refresh()

        def _hide() -> None:
            time.sleep(0.8)
            self._run_on_ui(self.test_overlay.patch, visible=False)
            self._run_on_ui(self._request_ui_refresh)

        threading.Thread(target=_hide, daemon=True).start()

    def _update_progress(self, percent: int) -> None:
        bounded = max(0, min(100, int(percent)))
        filled = int(32 * bounded / 100)
        bar = f"[{'#' * filled}{'-' * (32 - filled)}] {bounded}%"
        self.progress_text.patch(text=f"Overall Progress: {bounded}%")
        self.progress_bar_text.patch(text=bar)
        self._request_ui_refresh()

    def _set_status(self, text: str) -> None:
        self.status_text.patch(text=text)
        self._request_ui_refresh()

    def _append_log(self, line: str) -> None:
        self._log_lines.append(line)
        if len(self._log_lines) > 220:
            self._log_lines = self._log_lines[-220:]
        # Update the ui.Text content (use 'text' patch key for Text)
        self.log_text.patch(text="\n".join(self._log_lines))
        self._request_ui_refresh()

    def _safe_int(self, field, fallback: int) -> int:
        try:
            payload = field.to_dict().get("props", {})
            value = payload.get("value", str(fallback))
            return max(1, int(str(value).strip()))
        except Exception:
            return fallback

    def _run_on_ui(self, fn, *args, **kwargs) -> None:
        if self._ui_loop is None:
            try:
                fn(*args, **kwargs)
            except Exception:
                pass
            return
        try:
            self._ui_loop.call_soon_threadsafe(fn, *args, **kwargs)
        except Exception:
            try:
                fn(*args, **kwargs)
            except Exception:
                pass

    def _request_ui_refresh(self) -> None:
        if self._ui_loop is None:
            try:
                self.page.update()
            except Exception:
                pass
            return
        try:
            self._ui_loop.call_soon_threadsafe(self.page.update)
        except Exception:
            try:
                self.page.update()
            except Exception:
                pass


def _bootstrap(page: ui.Page) -> None:
    shell = TrainerShell(page)
    shell.mount()


def _pick_ui_port(start: int = 8890, span: int = 20) -> int:
    for port in range(start, start + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free local port found for ButterflyUI trainer")


def main() -> int:
    return ui.run_desktop(_bootstrap, host="127.0.0.1", port=_pick_ui_port())
