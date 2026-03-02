"""Abyss storage for OpenML v0.

Implements a durable SQLite + blob store with stable schema and trace APIs.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..types.core import TraceEvent, TraceSummary
from ..versions import SCHEMA_VERSION


def _now() -> int:
    return int(time.time())


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class AbyssStore:
    """SQLite-backed OpenML storage with a content-addressed blob directory."""

    _ALLOWED_ARTIFACT_KINDS = {"patch", "file", "report", "log"}
    _MIGRATIONS: dict[int, list[str]] = {}

    def __init__(self, data_root: str | os.PathLike[str] = "data/openml") -> None:
        self.data_root = Path(data_root)
        self.data_root.mkdir(parents=True, exist_ok=True)

        self.db_path = self.data_root / "abyss.sqlite"
        self.blobs_dir = self.data_root / "blobs"
        self.blobs_dir.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

        self._init_schema()

    # ── Schema/bootstrap ──────────────────────────────────────────

    def _init_schema(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        sql = schema_path.read_text(encoding="utf-8")
        self.conn.executescript(sql)
        self._set_meta("schema_version", str(SCHEMA_VERSION))
        self.conn.commit()

    @contextmanager
    def _transaction(self):
        try:
            self.conn.execute("BEGIN")
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            (key, value),
        )

    def _get_meta(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return str(row["value"])

    def get_schema_version(self) -> str:
        value = self._get_meta("schema_version")
        return value or ""

    def upgrade_schema(self, target_version: int | None = None) -> str:
        """Upgrade schema using migration-ready contract.

        For v0, no forward migrations are required yet, but this method provides
        a stable upgrade path and guards unsupported version transitions.
        """
        current_raw = self.get_schema_version() or "0"
        try:
            current = int(current_raw)
        except ValueError as exc:
            raise ValueError(f"Invalid schema_version in meta: {current_raw}") from exc

        latest = int(SCHEMA_VERSION)
        target = latest if target_version is None else int(target_version)

        if target > latest:
            raise ValueError(
                f"Requested target schema {target} exceeds supported version {latest}"
            )
        if current > latest:
            raise ValueError(
                f"Database schema {current} is newer than runtime supported version {latest}"
            )
        if current == target:
            return str(target)

        version = current
        while version < target:
            next_version = version + 1
            statements = self._MIGRATIONS.get(next_version, [])
            with self._transaction():
                for statement in statements:
                    self.conn.executescript(statement)
                self._set_meta("schema_version", str(next_version))
            version = next_version

        return str(version)

    # ── Blob helpers ──────────────────────────────────────────────

    def _write_blob(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        blob_path = self.blobs_dir / f"{digest}.blob"
        if not blob_path.exists():
            blob_path.write_bytes(data)
        return digest

    def load_blob(self, blob_ref: str) -> bytes:
        blob_path = self.blobs_dir / f"{blob_ref}.blob"
        payload = blob_path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != blob_ref:
            raise ValueError(f"Blob integrity check failed for ref: {blob_ref}")
        return payload

    def _coerce_blob_bytes(self, payload: Any) -> bytes:
        if payload is None:
            return b""
        if isinstance(payload, bytes):
            return payload
        if isinstance(payload, str):
            return payload.encode("utf-8")
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    # ── Workspace/documents ───────────────────────────────────────

    def create_workspace(self, root_path: str) -> str:
        normalized_root = str(Path(root_path).resolve())
        now = _now()
        existing = self.conn.execute(
            "SELECT id FROM workspaces WHERE root_path = ?",
            (normalized_root,),
        ).fetchone()
        if existing is not None:
            workspace_id = str(existing["id"])
            with self._transaction():
                self.conn.execute(
                    "UPDATE workspaces SET updated_at = ? WHERE id = ?",
                    (now, workspace_id),
                )
            return workspace_id

        workspace_id = _new_id("ws")
        with self._transaction():
            self.conn.execute(
                "INSERT INTO workspaces(id, root_path, created_at, updated_at) VALUES(?,?,?,?)",
                (workspace_id, normalized_root, now, now),
            )
        return workspace_id

    def _workspace_exists(self, workspace_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM workspaces WHERE id = ?",
            (workspace_id,),
        ).fetchone()
        return row is not None

    def _workspace_root(self, workspace_id: str) -> Path:
        row = self.conn.execute(
            "SELECT root_path FROM workspaces WHERE id = ?",
            (workspace_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown workspace_id: {workspace_id}")
        return Path(str(row["root_path"])).resolve()

    def _infer_mime(self, file_path: Path) -> str | None:
        mime, _encoding = mimetypes.guess_type(str(file_path))
        return mime

    def _trace_exists(self, trace_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM traces WHERE id = ?",
            (trace_id,),
        ).fetchone()
        return row is not None

    def _ensure_session(self, session_id: str, workspace_id: str) -> None:
        now = _now()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO sessions(id, workspace_id, title, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (session_id, workspace_id, "Untitled", now, now),
        )

    def upsert_document(
        self,
        workspace_id: str,
        path: str,
        content: bytes | str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        if not self._workspace_exists(workspace_id):
            raise ValueError(f"Unknown workspace_id: {workspace_id}")

        metadata = metadata or {}

        payload = content if isinstance(content, bytes) else content.encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        size_bytes = int(metadata.get("size_bytes", len(payload)))
        mtime = int(metadata.get("mtime", _now()))
        mime = metadata.get("mime")
        ingested_at = _now()

        existing = self.conn.execute(
            "SELECT id FROM documents WHERE workspace_id = ? AND path = ?",
            (workspace_id, path),
        ).fetchone()
        if existing is None:
            document_id = _new_id("doc")
            with self._transaction():
                self.conn.execute(
                    """
                    INSERT INTO documents(
                        id, workspace_id, path, sha256, size_bytes, mtime, mime, ingested_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (document_id, workspace_id, path, digest, size_bytes, mtime, mime, ingested_at),
                )
                self.conn.execute(
                    "UPDATE workspaces SET updated_at = ? WHERE id = ?",
                    (_now(), workspace_id),
                )
        else:
            document_id = str(existing["id"])
            with self._transaction():
                self.conn.execute(
                    """
                    UPDATE documents
                    SET sha256 = ?, size_bytes = ?, mtime = ?, mime = ?, ingested_at = ?
                    WHERE id = ?
                    """,
                    (digest, size_bytes, mtime, mime, ingested_at, document_id),
                )
                self.conn.execute(
                    "UPDATE workspaces SET updated_at = ? WHERE id = ?",
                    (_now(), workspace_id),
                )

        return document_id

    def list_documents(self, workspace_id: str) -> list[dict[str, Any]]:
        if not self._workspace_exists(workspace_id):
            raise ValueError(f"Unknown workspace_id: {workspace_id}")

        rows = self.conn.execute(
            """
            SELECT id, path, sha256, size_bytes, mtime, mime, ingested_at
            FROM documents
            WHERE workspace_id = ?
            ORDER BY path ASC
            """,
            (workspace_id,),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "path": str(row["path"]),
                "sha256": str(row["sha256"]),
                "size_bytes": int(row["size_bytes"]),
                "mtime": int(row["mtime"]),
                "mime": row["mime"],
                "ingested_at": int(row["ingested_at"]),
            }
            for row in rows
        ]

    def ingest_workspace(
        self,
        workspace_id: str,
        *,
        exclude_dirs: set[str] | None = None,
        max_file_bytes: int = 2_000_000,
    ) -> dict[str, int]:
        """Scan a workspace and upsert indexed documents.

        A2 goals:
        - stable relative paths
        - mime inference
        - deterministic re-ingest behavior (new/updated/unchanged)
        """
        if max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")

        root = self._workspace_root(workspace_id)
        if not root.exists() or not root.is_dir():
            raise ValueError(f"Workspace root is not a directory: {root}")

        excluded = set(exclude_dirs or set())
        if not excluded:
            excluded = {".git", ".hg", ".svn", "__pycache__", "node_modules", "env", ".venv"}

        existing_docs = {
            str(row["path"]): str(row["sha256"])
            for row in self.conn.execute(
                "SELECT path, sha256 FROM documents WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchall()
        }

        scanned = 0
        indexed = 0
        created = 0
        updated = 0
        unchanged = 0
        skipped = 0
        errors = 0

        for current_root, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted([d for d in dirnames if d not in excluded])
            for filename in sorted(filenames):
                scanned += 1
                abs_path = Path(current_root) / filename

                try:
                    stat = abs_path.stat()
                except OSError:
                    errors += 1
                    continue

                if not abs_path.is_file():
                    skipped += 1
                    continue

                if stat.st_size > max_file_bytes:
                    skipped += 1
                    continue

                try:
                    payload = abs_path.read_bytes()
                except OSError:
                    errors += 1
                    continue

                rel = abs_path.resolve().relative_to(root).as_posix()
                digest = hashlib.sha256(payload).hexdigest()
                previous = existing_docs.get(rel)

                if previous is None:
                    created += 1
                elif previous != digest:
                    updated += 1
                else:
                    unchanged += 1
                    continue

                self.upsert_document(
                    workspace_id,
                    rel,
                    payload,
                    {
                        "size_bytes": int(stat.st_size),
                        "mtime": int(stat.st_mtime),
                        "mime": self._infer_mime(abs_path),
                    },
                )
                indexed += 1

        return {
            "scanned": scanned,
            "indexed": indexed,
            "new": created,
            "updated": updated,
            "unchanged": unchanged,
            "skipped": skipped,
            "errors": errors,
        }

    # ── Trace lifecycle ───────────────────────────────────────────

    def start_trace(self, session_id: str, workspace_id: str, summary: str | None = None) -> str:
        if not self._workspace_exists(workspace_id):
            raise ValueError(f"Unknown workspace_id: {workspace_id}")

        trace_id = _new_id("trace")
        now = _now()

        with self._transaction():
            self._ensure_session(session_id, workspace_id)
            self.conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            self.conn.execute(
                """
                INSERT INTO traces(id, session_id, workspace_id, created_at, summary, status, metrics_json, blob_ref)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (trace_id, session_id, workspace_id, now, summary, "running", None, None),
            )
        return trace_id

    def append_trace_event(self, trace_id: str, event_type: str, data: dict[str, Any]) -> str:
        if not event_type.strip():
            raise ValueError("event_type must be non-empty")

        if not self._trace_exists(trace_id):
            raise ValueError(f"Unknown trace_id: {trace_id}")

        event_id = _new_id("evt")
        now = _now()

        row = self.conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM trace_events WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
        next_seq = int(row["max_seq"]) + 1 if row is not None else 1

        with self._transaction():
            self.conn.execute(
                """
                INSERT INTO trace_events(id, trace_id, seq, ts, type, data_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    trace_id,
                    next_seq,
                    now,
                    event_type,
                    json.dumps(data, ensure_ascii=False),
                ),
            )
        return event_id

    def finish_trace(
        self,
        trace_id: str,
        status: str,
        metrics: dict[str, Any] | None = None,
        blob_optional: bytes | str | dict[str, Any] | None = None,
    ) -> None:
        if not self._trace_exists(trace_id):
            raise ValueError(f"Unknown trace_id: {trace_id}")

        metrics_json = json.dumps(metrics or {}, ensure_ascii=False)
        blob_ref: str | None = None
        if blob_optional is not None:
            blob_ref = self._write_blob(self._coerce_blob_bytes(blob_optional))

        with self._transaction():
            self.conn.execute(
                "UPDATE traces SET status = ?, metrics_json = ?, blob_ref = ? WHERE id = ?",
                (status, metrics_json, blob_ref, trace_id),
            )

    def record_outcome(
        self,
        trace_id: str,
        success: bool,
        exit_code: int | None = None,
        error_type: str | None = None,
        error_summary: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> str:
        if not self._trace_exists(trace_id):
            raise ValueError(f"Unknown trace_id: {trace_id}")

        outcome_id = _new_id("out")
        with self._transaction():
            self.conn.execute(
                """
                INSERT INTO outcomes(
                    id, trace_id, success, exit_code, error_type, error_summary, data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outcome_id,
                    trace_id,
                    1 if success else 0,
                    exit_code,
                    error_type,
                    error_summary,
                    json.dumps(data or {}, ensure_ascii=False),
                ),
            )
        return outcome_id

    def add_artifact(
        self,
        trace_id: str,
        kind: str,
        *,
        path: str | None = None,
        content: bytes | str | dict[str, Any] | None = None,
    ) -> str:
        if not self._trace_exists(trace_id):
            raise ValueError(f"Unknown trace_id: {trace_id}")

        normalized_kind = kind.strip().lower()
        if normalized_kind not in self._ALLOWED_ARTIFACT_KINDS:
            raise ValueError(
                f"Invalid artifact kind: {kind}. Allowed: {sorted(self._ALLOWED_ARTIFACT_KINDS)}"
            )

        artifact_id = _new_id("art")
        created_at = _now()

        sha256: str | None = None
        blob_ref: str | None = None

        if content is not None:
            payload = self._coerce_blob_bytes(content)
            sha256 = hashlib.sha256(payload).hexdigest()
            blob_ref = self._write_blob(payload)

        with self._transaction():
            self.conn.execute(
                """
                INSERT INTO artifacts(id, trace_id, path, kind, sha256, blob_ref, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (artifact_id, trace_id, path, normalized_kind, sha256, blob_ref, created_at),
            )
        return artifact_id

    def recover_incomplete_traces(self, max_age_seconds: int = 600) -> int:
        """Mark stale running traces as error to recover from interrupted writes.

        Recovery criteria:
        - trace status is `running`
        - no outcome row exists
        - trace age exceeds max_age_seconds
        """
        if max_age_seconds < 0:
            raise ValueError("max_age_seconds must be >= 0")

        threshold = _now() - int(max_age_seconds)
        rows = self.conn.execute(
            """
            SELECT t.id
            FROM traces t
            LEFT JOIN outcomes o ON o.trace_id = t.id
            WHERE t.status = 'running'
              AND t.created_at <= ?
              AND o.id IS NULL
            """,
            (threshold,),
        ).fetchall()
        trace_ids = [str(row["id"]) for row in rows]

        for trace_id in trace_ids:
            self.finish_trace(
                trace_id,
                status="error",
                metrics={"recovered": True, "reason": "stale_running_trace"},
            )
            self.record_outcome(
                trace_id,
                success=False,
                exit_code=None,
                error_type="recovered_incomplete",
                error_summary="Recovered stale running trace after interruption",
                data={"max_age_seconds": int(max_age_seconds)},
            )

        return len(trace_ids)

    def run_integrity_checks(self, *, verify_blob_hashes: bool = False) -> dict[str, Any]:
        """Run DB and trace integrity checks for A4 hardening."""
        fk_rows = self.conn.execute("PRAGMA foreign_key_check").fetchall()

        seq_gaps: list[dict[str, Any]] = []
        trace_rows = self.conn.execute(
            "SELECT DISTINCT trace_id FROM trace_events ORDER BY trace_id"
        ).fetchall()
        for trace_row in trace_rows:
            trace_id = str(trace_row["trace_id"])
            seqs = [
                int(row["seq"])
                for row in self.conn.execute(
                    "SELECT seq FROM trace_events WHERE trace_id = ? ORDER BY seq ASC",
                    (trace_id,),
                ).fetchall()
            ]
            expected = list(range(1, len(seqs) + 1))
            if seqs != expected:
                seq_gaps.append(
                    {
                        "trace_id": trace_id,
                        "actual": seqs,
                        "expected": expected,
                    }
                )

        blob_errors: list[dict[str, str]] = []
        if verify_blob_hashes:
            blob_refs: set[str] = set()

            for row in self.conn.execute(
                "SELECT blob_ref FROM traces WHERE blob_ref IS NOT NULL"
            ).fetchall():
                blob_refs.add(str(row["blob_ref"]))

            for row in self.conn.execute(
                "SELECT blob_ref FROM artifacts WHERE blob_ref IS NOT NULL"
            ).fetchall():
                blob_refs.add(str(row["blob_ref"]))

            for blob_ref in sorted(blob_refs):
                blob_path = self.blobs_dir / f"{blob_ref}.blob"
                if not blob_path.exists():
                    blob_errors.append({"blob_ref": blob_ref, "error": "missing_blob"})
                    continue
                try:
                    self.load_blob(blob_ref)
                except Exception as exc:
                    blob_errors.append({"blob_ref": blob_ref, "error": str(exc)})

        ok = (len(fk_rows) == 0) and (len(seq_gaps) == 0) and (len(blob_errors) == 0)

        return {
            "ok": ok,
            "foreign_key_violations": [dict(row) for row in fk_rows],
            "trace_sequence_issues": seq_gaps,
            "blob_issues": blob_errors,
        }

    def list_artifacts(self, trace_id: str) -> list[dict[str, Any]]:
        if not self._trace_exists(trace_id):
            raise ValueError(f"Unknown trace_id: {trace_id}")

        rows = self.conn.execute(
            """
            SELECT id, trace_id, path, kind, sha256, blob_ref, created_at
            FROM artifacts
            WHERE trace_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (trace_id,),
        ).fetchall()

        return [
            {
                "id": str(row["id"]),
                "trace_id": str(row["trace_id"]),
                "path": row["path"],
                "kind": str(row["kind"]),
                "sha256": row["sha256"],
                "blob_ref": row["blob_ref"],
                "created_at": int(row["created_at"]),
            }
            for row in rows
        ]

    def load_artifact(self, artifact_id: str, *, include_blob: bool = False) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT id, trace_id, path, kind, sha256, blob_ref, created_at
            FROM artifacts
            WHERE id = ?
            """,
            (artifact_id,),
        ).fetchone()
        if row is None:
            return {}

        result: dict[str, Any] = {
            "id": str(row["id"]),
            "trace_id": str(row["trace_id"]),
            "path": row["path"],
            "kind": str(row["kind"]),
            "sha256": row["sha256"],
            "blob_ref": row["blob_ref"],
            "created_at": int(row["created_at"]),
        }

        if include_blob and row["blob_ref"]:
            blob_bytes = self.load_blob(str(row["blob_ref"]))
            result["blob_bytes"] = blob_bytes

        return result

    # ── Query APIs ────────────────────────────────────────────────

    def list_recent_traces(self, workspace_id: str, limit: int = 20) -> list[TraceSummary]:
        rows = self.conn.execute(
            """
            SELECT id, session_id, workspace_id, created_at, summary, status, metrics_json
            FROM traces
            WHERE workspace_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (workspace_id, limit),
        ).fetchall()

        traces: list[TraceSummary] = []
        for row in rows:
            metrics = json.loads(row["metrics_json"]) if row["metrics_json"] else {}
            traces.append(
                TraceSummary(
                    trace_id=str(row["id"]),
                    session_id=str(row["session_id"]),
                    workspace_id=str(row["workspace_id"]),
                    created_at=int(row["created_at"]),
                    summary=row["summary"],
                    status=str(row["status"]),
                    metrics=metrics,
                )
            )
        return traces

    def load_trace(self, trace_id: str) -> dict[str, Any]:
        trace = self.conn.execute(
            """
            SELECT id, session_id, workspace_id, created_at, summary, status, metrics_json, blob_ref
            FROM traces
            WHERE id = ?
            """,
            (trace_id,),
        ).fetchone()
        if trace is None:
            return {}

        events_rows = self.conn.execute(
            """
            SELECT id, trace_id, seq, ts, type, data_json
            FROM trace_events
            WHERE trace_id = ?
            ORDER BY seq ASC
            """,
            (trace_id,),
        ).fetchall()

        events: list[TraceEvent] = []
        for row in events_rows:
            events.append(
                TraceEvent(
                    event_id=str(row["id"]),
                    trace_id=str(row["trace_id"]),
                    seq=int(row["seq"]),
                    ts=int(row["ts"]),
                    event_type=str(row["type"]),
                    data=json.loads(row["data_json"]),
                )
            )

        outcome = self.conn.execute(
            """
            SELECT id, success, exit_code, error_type, error_summary, data_json
            FROM outcomes
            WHERE trace_id = ?
            ORDER BY rowid DESC
            LIMIT 1
            """,
            (trace_id,),
        ).fetchone()

        return {
            "trace": {
                "id": str(trace["id"]),
                "session_id": str(trace["session_id"]),
                "workspace_id": str(trace["workspace_id"]),
                "created_at": int(trace["created_at"]),
                "summary": trace["summary"],
                "status": str(trace["status"]),
                "metrics": json.loads(trace["metrics_json"]) if trace["metrics_json"] else {},
                "blob_ref": trace["blob_ref"],
            },
            "events": [
                {
                    "id": e.event_id,
                    "trace_id": e.trace_id,
                    "seq": e.seq,
                    "ts": e.ts,
                    "type": e.event_type,
                    "data": e.data,
                }
                for e in events
            ],
            "outcome": (
                {
                    "id": str(outcome["id"]),
                    "success": int(outcome["success"]),
                    "exit_code": outcome["exit_code"],
                    "error_type": outcome["error_type"],
                    "error_summary": outcome["error_summary"],
                    "data": json.loads(outcome["data_json"]) if outcome["data_json"] else {},
                }
                if outcome is not None
                else None
            ),
            "artifacts": self.list_artifacts(trace_id),
        }

    def close(self) -> None:
        self.conn.close()
