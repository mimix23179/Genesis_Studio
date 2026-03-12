from __future__ import annotations

import html
import json
import logging
import math
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

import requests

logger = logging.getLogger("genesis.ollama.library")


@dataclass(frozen=True)
class OllamaLibraryEntry:
    name: str
    description: str
    capabilities: list[str] = field(default_factory=list)
    variants: list[str] = field(default_factory=list)
    pulls: str = ""
    tags: str = ""
    updated: str = ""
    updated_title: str = ""
    library_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OllamaLibraryDetail:
    name: str
    description: str
    capabilities: list[str] = field(default_factory=list)
    variants: list[str] = field(default_factory=list)
    pulls: str = ""
    tags: str = ""
    updated: str = ""
    updated_title: str = ""
    library_url: str = ""
    readme_markdown: str = ""
    pull_targets: list[str] = field(default_factory=list)
    default_pull_target: str = ""
    rating_text: str = "N/A"
    rating_note: str = "Ollama Library does not expose user ratings."
    popularity_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OllamaDownloadState:
    download_id: str
    model: str
    base_url: str
    status: str = "Queued"
    message: str = "Queued"
    progress: float | None = None
    completed: int | None = None
    total: int | None = None
    done: bool = False
    paused: bool = False
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def snapshot(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["progress_percent"] = None if self.progress is None else int(round(self.progress * 100))
        return payload


class OllamaLibraryService:
    """Fetches Ollama public catalog pages and extracts model metadata."""

    _BASE_URL = "https://ollama.com"
    _CATALOG_TTL_S = 300.0
    _DETAIL_TTL_S = 600.0

    def __init__(self, *, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "GenesisStudio/1.0 (+https://ollama.com/library)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        self._catalog_cache: tuple[float, list[OllamaLibraryEntry]] | None = None
        self._detail_cache: dict[str, tuple[float, OllamaLibraryDetail]] = {}
        self._lock = threading.Lock()

    def list_catalog(self, *, force: bool = False) -> list[OllamaLibraryEntry]:
        with self._lock:
            cached = self._catalog_cache
            if not force and cached is not None and (time.time() - cached[0]) < self._CATALOG_TTL_S:
                return list(cached[1])

        response = self._session.get(f"{self._BASE_URL}/library", timeout=20)
        response.raise_for_status()
        entries = self._parse_catalog(response.text)

        with self._lock:
            self._catalog_cache = (time.time(), entries)
        return list(entries)

    def get_detail(self, model_name: str, *, force: bool = False) -> OllamaLibraryDetail:
        target = str(model_name or "").strip().lower()
        if not target:
            raise ValueError("Model name is required.")

        with self._lock:
            cached = self._detail_cache.get(target)
            if not force and cached is not None and (time.time() - cached[0]) < self._DETAIL_TTL_S:
                return cached[1]

        response = self._session.get(f"{self._BASE_URL}/library/{target}", timeout=20)
        response.raise_for_status()
        detail = self._parse_detail(target, response.text)

        with self._lock:
            self._detail_cache[target] = (time.time(), detail)
        return detail

    def _parse_catalog(self, html_text: str) -> list[OllamaLibraryEntry]:
        entries: list[OllamaLibraryEntry] = []
        seen: set[str] = set()
        pattern = re.compile(
            r'<li\s+[^>]*x-test-model[^>]*>(?P<body>.*?)</li>',
            re.IGNORECASE | re.DOTALL,
        )

        for match in pattern.finditer(html_text):
            block = match.group("body")
            name = self._extract_first(block, r'href="/library/(?P<value>[^"]+)"')
            if not name or name in seen:
                continue
            seen.add(name)
            entries.append(
                OllamaLibraryEntry(
                    name=name,
                    description=self._clean_text(
                        self._extract_first(
                            block,
                            r'<p\s+[^>]*text-neutral-800[^>]*>(?P<value>.*?)</p>',
                        )
                    ),
                    capabilities=self._extract_all(block, r'x-test-capability[^>]*>(?P<value>.*?)</span>'),
                    variants=self._extract_all(block, r'x-test-size[^>]*>(?P<value>.*?)</span>'),
                    pulls=self._clean_text(self._extract_first(block, r'x-test-pull-count[^>]*>(?P<value>.*?)</span>')),
                    tags=self._clean_text(self._extract_first(block, r'x-test-tag-count[^>]*>(?P<value>.*?)</span>')),
                    updated=self._clean_text(self._extract_first(block, r'x-test-updated[^>]*>(?P<value>.*?)</span>')),
                    updated_title="",
                    library_url=f"{self._BASE_URL}/library/{name}",
                )
            )
        return entries

    def _parse_detail(self, model_name: str, html_text: str) -> OllamaLibraryDetail:
        meta_description = self._clean_text(
            self._extract_first(html_text, r'<meta\s+name="description"\s+content="(?P<value>[^"]*)"')
        )
        readme_raw = self._extract_textarea_value(html_text, marker='name="markdown"')
        if not readme_raw:
            readme_raw = self._extract_textarea_value(html_text, marker='id="editor"')
        readme_markdown = html.unescape(readme_raw).strip()
        capabilities = self._extract_all(html_text, r'x-test-capability[^>]*>(?P<value>.*?)</span>')
        variants = self._extract_all(html_text, r'x-test-size[^>]*>(?P<value>.*?)</span>')
        pull_targets = self._build_pull_targets(model_name, variants, readme_markdown)
        pulls_text = self._clean_text(self._extract_first(html_text, r'x-test-pull-count[^>]*>(?P<value>.*?)</span>'))

        return OllamaLibraryDetail(
            name=model_name,
            description=meta_description,
            capabilities=capabilities,
            variants=variants,
            pulls=pulls_text,
            tags=self._clean_text(self._extract_first(html_text, r'x-test-tag-count[^>]*>(?P<value>.*?)</span>')),
            updated=self._clean_text(self._extract_first(html_text, r'x-test-updated[^>]*>(?P<value>.*?)</span>')),
            updated_title="",
            library_url=f"{self._BASE_URL}/library/{model_name}",
            readme_markdown=readme_markdown,
            pull_targets=pull_targets,
            default_pull_target=pull_targets[0] if pull_targets else model_name,
            popularity_score=self._popularity_score(pulls_text),
        )

    @staticmethod
    def _clean_text(value: str) -> str:
        cleaned = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
        return re.sub(r"\s+", " ", cleaned).strip()

    @classmethod
    def _extract_first(
        cls,
        text: str,
        pattern: str,
        *,
        default: str = "",
        flags: int = re.IGNORECASE | re.DOTALL,
    ) -> str:
        match = re.search(pattern, text or "", flags)
        if not match:
            return default
        value = match.groupdict().get("value")
        if value is None and match.groups():
            value = match.group(1)
        return str(value or default)

    @classmethod
    def _extract_all(
        cls,
        text: str,
        pattern: str,
        *,
        flags: int = re.IGNORECASE | re.DOTALL,
    ) -> list[str]:
        values: list[str] = []
        for match in re.finditer(pattern, text or "", flags):
            value = match.groupdict().get("value")
            if value is None and match.groups():
                value = match.group(1)
            cleaned = cls._clean_text(str(value or ""))
            if cleaned and cleaned not in values:
                values.append(cleaned)
        return values

    @staticmethod
    def _extract_textarea_value(text: str, *, marker: str) -> str:
        source = text or ""
        anchor = source.find(marker)
        if anchor < 0:
            return ""
        start = source.find(">", anchor)
        if start < 0:
            return ""
        end = source.find("</textarea", start)
        if end < 0:
            return ""
        return source[start + 1 : end]

    @staticmethod
    def _build_pull_targets(model_name: str, variants: list[str], readme_markdown: str) -> list[str]:
        targets: list[str] = []
        for match in re.finditer(r"ollama\s+run\s+([A-Za-z0-9_.:-]+)", readme_markdown or ""):
            target = str(match.group(1) or "").strip()
            if target and target not in targets:
                targets.append(target)
        if targets:
            return targets
        if not variants:
            return [model_name]
        for variant in variants:
            target = f"{model_name}:{variant}"
            if target not in targets:
                targets.append(target)
        return targets or [model_name]

    @staticmethod
    def _popularity_score(pulls_text: str) -> float | None:
        raw = str(pulls_text or "").strip().upper()
        if not raw:
            return None
        multiplier = 1.0
        if raw.endswith("M"):
            multiplier = 1_000_000.0
            raw = raw[:-1]
        elif raw.endswith("K"):
            multiplier = 1_000.0
            raw = raw[:-1]
        try:
            pulls = float(raw) * multiplier
        except Exception:
            return None
        if pulls <= 0:
            return 0.0
        score = min(5.0, max(1.0, math.log10(pulls) - 0.5))
        return round(score, 1)


class OllamaDownloadManager:
    """Streams Ollama pull progress and keeps UI-friendly download state."""

    def __init__(
        self,
        *,
        timeout: float = 900.0,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.timeout = max(60.0, float(timeout))
        self._on_update = on_update
        self._downloads: dict[str, OllamaDownloadState] = {}
        self._active_by_model: dict[str, str] = {}
        self._controls: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def list_downloads(self) -> list[dict[str, Any]]:
        with self._lock:
            items = [state.snapshot() for state in self._downloads.values()]
        return sorted(items, key=lambda item: float(item.get("started_at", 0.0)), reverse=True)

    def start_download(self, *, model: str, base_url: str) -> dict[str, Any]:
        target_model = str(model or "").strip()
        target_base = str(base_url or "").strip().rstrip("/")
        if not target_model:
            raise ValueError("Download model cannot be empty.")
        if not target_base:
            raise ValueError("Ollama base URL cannot be empty.")

        with self._lock:
            existing_id = self._active_by_model.get(target_model)
            if existing_id:
                existing = self._downloads.get(existing_id)
                if existing is not None and not existing.done and not existing.paused:
                    return existing.snapshot()

            download_id = str(uuid.uuid4())
            state = OllamaDownloadState(
                download_id=download_id,
                model=target_model,
                base_url=target_base,
                status="Queued",
                message=f"Queued {target_model}",
            )
            self._downloads[download_id] = state
            self._active_by_model[target_model] = download_id
            self._controls[download_id] = {"response": None}

        self._emit(state)
        self._spawn_download_thread(download_id, target_model)
        return state.snapshot()

    def pause_download(self, download_id: str) -> dict[str, Any]:
        target_id = str(download_id or "").strip()
        if not target_id:
            raise ValueError("Download id is required.")

        with self._lock:
            state = self._downloads.get(target_id)
            if state is None:
                raise KeyError(f"Unknown download id: {target_id}")
            if state.done or state.paused:
                return state.snapshot()
            state.paused = True
            state.status = "Paused"
            state.message = f"Paused {state.model}"
            response = self._controls.get(target_id, {}).get("response")
            snapshot = state.snapshot()
        if response is not None:
            try:
                response.close()
            except Exception:
                logger.debug("Failed to close paused download response %s", target_id)
        self._emit_snapshot(snapshot)
        return snapshot

    def resume_download(self, download_id: str) -> dict[str, Any]:
        target_id = str(download_id or "").strip()
        if not target_id:
            raise ValueError("Download id is required.")

        with self._lock:
            state = self._downloads.get(target_id)
            if state is None:
                raise KeyError(f"Unknown download id: {target_id}")
            if state.done and not state.error:
                return state.snapshot()
            state.done = False
            state.paused = False
            state.error = None
            state.finished_at = None
            state.status = "Queued"
            state.message = f"Resuming {state.model}"
            self._active_by_model[state.model] = target_id
            self._controls.setdefault(target_id, {})["response"] = None
            snapshot = state.snapshot()
            model = state.model
        self._emit_snapshot(snapshot)
        self._spawn_download_thread(target_id, model)
        return snapshot

    def _spawn_download_thread(self, download_id: str, model: str) -> None:
        thread = threading.Thread(
            target=self._run_download,
            args=(download_id,),
            daemon=True,
            name=f"ollama-download-{model}",
        )
        thread.start()

    def _run_download(self, download_id: str) -> None:
        state = self._downloads.get(download_id)
        if state is None:
            return

        self._update(download_id, status="Preparing", message=f"Starting download for {state.model}")
        try:
            response = requests.post(
                f"{state.base_url}/api/pull",
                json={"name": state.model, "stream": True},
                stream=True,
                timeout=self.timeout,
            )
            with self._lock:
                self._controls.setdefault(download_id, {})["response"] = response
            response.raise_for_status()
            self._update(download_id, status="Downloading", message=f"Downloading {state.model}", paused=False, error=None)

            for raw_line in response.iter_lines(decode_unicode=True):
                current = self._downloads.get(download_id)
                if current is not None and current.paused:
                    return
                if not raw_line:
                    continue
                try:
                    payload = json.loads(raw_line)
                except json.JSONDecodeError:
                    logger.debug("Ignoring non-JSON Ollama pull line: %s", raw_line)
                    continue

                if isinstance(payload, dict) and payload.get("error"):
                    raise RuntimeError(str(payload.get("error")))

                completed = payload.get("completed") if isinstance(payload, dict) else None
                total = payload.get("total") if isinstance(payload, dict) else None
                progress = None
                if isinstance(completed, (int, float)) and isinstance(total, (int, float)) and float(total) > 0:
                    progress = min(1.0, max(0.0, float(completed) / float(total)))

                status = str(payload.get("status", "Downloading")).strip() if isinstance(payload, dict) else "Downloading"
                done = status.lower() in {"success", "done"}
                message = status or f"Downloading {state.model}"
                self._update(
                    download_id,
                    status=status or "Downloading",
                    message=message,
                    completed=int(completed) if isinstance(completed, (int, float)) else None,
                    total=int(total) if isinstance(total, (int, float)) else None,
                    progress=progress,
                    done=done,
                    paused=False,
                    error=None,
                    finished_at=time.time() if done else None,
                )
                if done:
                    break

            final = self._downloads.get(download_id)
            if final is not None and final.paused:
                return
            if final is not None and not final.done:
                self._update(
                    download_id,
                    status="Complete",
                    message=f"Download complete: {state.model}",
                    progress=1.0,
                    done=True,
                    paused=False,
                    error=None,
                    finished_at=time.time(),
                )
        except Exception as exc:
            current = self._downloads.get(download_id)
            if current is not None and current.paused:
                self._update(download_id, status="Paused", message=f"Paused {current.model}", error=None, done=False, finished_at=None)
                return
            self._update(
                download_id,
                status="Failed",
                message=f"Download failed: {state.model}",
                error=str(exc),
                done=True,
                paused=False,
                finished_at=time.time(),
            )
        finally:
            with self._lock:
                self._controls.setdefault(download_id, {})["response"] = None
                active_id = self._active_by_model.get(state.model)
                if active_id == download_id:
                    self._active_by_model.pop(state.model, None)

    def _update(self, download_id: str, **changes: Any) -> None:
        with self._lock:
            state = self._downloads.get(download_id)
            if state is None:
                return
            for key, value in changes.items():
                if value is None and key not in {"completed", "total", "progress", "finished_at"}:
                    continue
                setattr(state, key, value)
            state.updated_at = time.time()
            snapshot = state.snapshot()
        self._emit_snapshot(snapshot)

    def _emit(self, state: OllamaDownloadState) -> None:
        self._emit_snapshot(state.snapshot())

    def _emit_snapshot(self, snapshot: dict[str, Any]) -> None:
        if callable(self._on_update):
            try:
                self._on_update(snapshot)
            except Exception:
                logger.exception("Download update callback failed")