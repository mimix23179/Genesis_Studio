PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    root_path TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(root_path)
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    title TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    mtime INTEGER NOT NULL,
    mime TEXT,
    ingested_at INTEGER NOT NULL,
    UNIQUE(workspace_id, path),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);

CREATE TABLE IF NOT EXISTS traces (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    summary TEXT,
    status TEXT NOT NULL,
    metrics_json TEXT,
    blob_ref TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);

CREATE TABLE IF NOT EXISTS trace_events (
    id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    type TEXT NOT NULL,
    data_json TEXT NOT NULL,
    FOREIGN KEY (trace_id) REFERENCES traces(id)
);

CREATE INDEX IF NOT EXISTS idx_trace_events_trace_seq
    ON trace_events(trace_id, seq);

CREATE UNIQUE INDEX IF NOT EXISTS uq_trace_events_trace_seq
    ON trace_events(trace_id, seq);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    path TEXT,
    kind TEXT NOT NULL,
    sha256 TEXT,
    blob_ref TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (trace_id) REFERENCES traces(id)
);

CREATE TABLE IF NOT EXISTS outcomes (
    id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    success INTEGER NOT NULL,
    exit_code INTEGER,
    error_type TEXT,
    error_summary TEXT,
    data_json TEXT,
    FOREIGN KEY (trace_id) REFERENCES traces(id)
);
