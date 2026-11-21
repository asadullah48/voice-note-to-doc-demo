"""Append-only audit table. It lives in the same SQLite file as draft state (see store.py).

Rows hold field names and SHA-256 content hashes, never transcript text or corrected values.
"""

import sqlite3
from datetime import UTC, datetime

OUTCOMES = ('ok', 'blocked', 'rejected', 'failed')

SCHEMA = """
CREATE TABLE audit (
    id INTEGER PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('ok', 'blocked', 'rejected', 'failed')),
    draft_id INTEGER REFERENCES drafts(id),
    reason_code TEXT NOT NULL DEFAULT '',
    before_hash TEXT,
    after_hash TEXT
);
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
"""


def insert(
    conn: sqlite3.Connection,
    actor: str,
    action: str,
    outcome: str,
    draft_id: int | None,
    reason_code: str,
    before_hash: str | None,
    after_hash: str | None,
) -> None:
    """Insert one row. Callers run it inside the transaction of the change it describes."""
    conn.execute(
        'INSERT INTO audit (ts_utc, actor, action, outcome, draft_id, reason_code, before_hash, after_hash)'
        ' VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (datetime.now(UTC).isoformat(), actor, action, outcome, draft_id, reason_code, before_hash, after_hash),
    )


def rows(conn: sqlite3.Connection, draft_id: int | None = None) -> list[sqlite3.Row]:
    if draft_id is None:
        return list(conn.execute('SELECT * FROM audit ORDER BY id'))
    return list(conn.execute('SELECT * FROM audit WHERE draft_id = ? ORDER BY id', (draft_id,)))
