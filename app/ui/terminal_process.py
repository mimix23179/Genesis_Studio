from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable, Sequence


class TerminalProcess:
	"""Manages a long-lived shell process for the embedded terminal."""

	def __init__(
		self,
		*,
		workspace_root: Path,
		on_output: Callable[[str], None],
		on_closed: Callable[[int | None], None] | None = None,
		preferred_shell: str | None = None,
	) -> None:
		self.workspace_root = workspace_root
		self.on_output = on_output
		self.on_closed = on_closed
		self.preferred_shell = preferred_shell

		self._process: subprocess.Popen[str] | None = None
		self._reader: threading.Thread | None = None
		self._lock = threading.Lock()

	def is_running(self) -> bool:
		return self._process is not None and self._process.poll() is None

	def start(self) -> bool:
		with self._lock:
			if self.is_running():
				return True

			command = self._resolve_shell_command(self.preferred_shell)
			if command is None:
				self.on_output("\r\nNo supported shell was found on this machine.\r\n")
				return False

			try:
				self._process = subprocess.Popen(
					command,
					cwd=str(self.workspace_root),
					stdin=subprocess.PIPE,
					stdout=subprocess.PIPE,
					stderr=subprocess.STDOUT,
					text=True,
					encoding="utf-8",
					errors="replace",
					bufsize=0,
				)
			except Exception as exc:
				self._process = None
				self.on_output(f"\r\nFailed to start terminal process: {exc}\r\n")
				return False

			self._reader = threading.Thread(target=self._pump_stdout, daemon=True)
			self._reader.start()
			return True

	def write_line(self, command: str) -> None:
		process = self._process
		if process is None or process.poll() is not None:
			self.on_output("\r\nTerminal process is not running.\r\n")
			return
		if process.stdin is None:
			return
		try:
			process.stdin.write(command + "\n")
			process.stdin.flush()
		except Exception:
			self.on_output("\r\nUnable to write to terminal process.\r\n")

	def stop(self) -> None:
		with self._lock:
			process = self._process
			self._process = None
		if process is None:
			return

		try:
			if process.stdin:
				process.stdin.write("exit\n")
				process.stdin.flush()
		except Exception:
			pass

		try:
			process.wait(timeout=0.8)
		except Exception:
			try:
				process.terminate()
			except Exception:
				pass

	def _pump_stdout(self) -> None:
		process = self._process
		if process is None or process.stdout is None:
			return

		try:
			while True:
				chunk = process.stdout.read(1)
				if chunk == "":
					break
				self.on_output(chunk)
		finally:
			code = None
			try:
				code = process.poll()
			except Exception:
				pass
			if self.on_closed:
				self.on_closed(code)

	@staticmethod
	def _resolve_shell_command(preferred_shell: str | None) -> Sequence[str] | None:
		if preferred_shell:
			candidate = preferred_shell.strip()
			if candidate:
				return [candidate]

		if os.name == "nt":
			candidates: list[Sequence[str]] = [
				["pwsh", "-NoLogo"],
				["powershell", "-NoLogo"],
				["cmd", "/Q"],
				["bash"],
			]
		else:
			candidates = [
				["bash"],
				["zsh"],
				["sh"],
			]

		for item in candidates:
			if shutil.which(item[0]):
				return item
		return None