"""Small local SQLite store for immutable source snapshots and source sets."""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from design2code.settings import get_settings


def _open_connection() -> sqlite3.Connection:
    root = get_settings().runtime_dir
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "design2code.sqlite", timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS inputs (
            id TEXT PRIMARY KEY, type TEXT NOT NULL, source_hash TEXT NOT NULL,
            data_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS source_sets (
            id TEXT NOT NULL, revision INTEGER NOT NULL, source_hash TEXT NOT NULL,
            data_json TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY (id, revision)
        );
        CREATE TABLE IF NOT EXISTS source_confirmations (
            set_id TEXT NOT NULL, revision INTEGER NOT NULL, source_hash TEXT NOT NULL,
            confirmed_at TEXT NOT NULL, PRIMARY KEY (set_id, revision)
        );
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, set_id TEXT NOT NULL, revision INTEGER NOT NULL,
            source_hash TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
            request_hash TEXT NOT NULL, status TEXT NOT NULL, calls INTEGER NOT NULL DEFAULT 0,
            repairs INTEGER NOT NULL DEFAULT 0, result_json TEXT, error TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS run_events (
            run_id TEXT NOT NULL, seq INTEGER NOT NULL, type TEXT NOT NULL,
            payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY (run_id, seq)
        );
        CREATE TABLE IF NOT EXISTS repair_requests (
            idempotency_key TEXT PRIMARY KEY, run_id TEXT NOT NULL,
            request_hash TEXT NOT NULL, created_at TEXT NOT NULL
        );
    """)
    return db


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    db = _open_connection()
    try:
        with db:
            yield db
    finally:
        db.close()


def identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def get_input(input_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM inputs WHERE id = ?", (input_id,)).fetchone()
    if row is None:
        return None
    return {"input_id": row["id"], "input_type": row["type"],
            "source_hash": row["source_hash"], "data": json.loads(row["data_json"])}


def get_source_set(set_id: str, revision: int | None = None) -> dict[str, Any] | None:
    with connect() as db:
        if revision is None:
            row = db.execute("SELECT * FROM source_sets WHERE id = ? ORDER BY revision DESC LIMIT 1", (set_id,)).fetchone()
        else:
            row = db.execute("SELECT * FROM source_sets WHERE id = ? AND revision = ?", (set_id, revision)).fetchone()
    if row is None:
        return None
    return {"source_set_id": row["id"], "source_set_revision": row["revision"],
            "source_set_hash": row["source_hash"], **json.loads(row["data_json"])}
