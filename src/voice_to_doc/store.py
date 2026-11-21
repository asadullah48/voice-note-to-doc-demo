"""Draft state and its audit log in ONE SQLite file, so a change and its audit row commit together."""

import json
import os
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from . import audit
from .draft import canonical, content_hash
from .models import Fields

SCHEMA_VERSION = 1
DB_ENV = 'VOICE_TO_DOC_DB'
DEFAULT_DB = 'voice_to_doc.db'

DRAFTS = """
CREATE TABLE drafts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    approval_actor TEXT,
    approval_ts_utc TEXT,
    approval_hash TEXT,
    exported_hash TEXT,
    exported_path TEXT,
    next_ts_utc TEXT
);
"""


class StoreError(Exception):
    """The database is missing, unreadable, or from a newer version of this tool."""


class UnknownDraft(StoreError, LookupError):
    pass


def default_db() -> Path:
    return Path(os.environ.get(DB_ENV) or DEFAULT_DB)


class Store:
    """Single-user SQLite store. ':memory:' is used by tests and the library default."""

    def __init__(self, path: Path | str = ':memory:', create: bool = True) -> None:
        self.path = path
        try:
            if str(path) == ':memory:':
                conn = sqlite3.connect(':memory:', isolation_level=None)
            else:
                file = Path(path)
                if not create and not file.is_file():
                    raise StoreError(f'database not found: {file} (run `extract` or `demo` first, or pass --db)')
                mode = 'rwc' if create else 'rw'
                conn = sqlite3.connect(f'{file.resolve().as_uri()}?mode={mode}', uri=True, isolation_level=None)
        except sqlite3.Error as error:
            raise StoreError(f'cannot open database {path}: {error}') from error
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA foreign_keys = ON')
            version = conn.execute('PRAGMA user_version').fetchone()[0]
            if version > SCHEMA_VERSION:
                raise StoreError(f'database {path} has schema version {version}; this tool knows {SCHEMA_VERSION}')
            if version == 0:
                conn.executescript(
                    f'BEGIN IMMEDIATE;{DRAFTS}{audit.SCHEMA}PRAGMA user_version = {SCHEMA_VERSION};COMMIT;'
                )
        except sqlite3.Error as error:
            if conn.in_transaction:
                conn.execute('ROLLBACK')
            conn.close()
            raise StoreError(f'cannot read database {path}: {error}') from error
        except StoreError:
            conn.close()
            raise
        self.conn = conn

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """One write transaction: everything inside commits together or rolls back together."""
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            yield self.conn
            self.conn.execute('COMMIT')
        except BaseException:
            if self.conn.in_transaction:
                self.conn.execute('ROLLBACK')
            raise

    def row(self, draft_id: int) -> sqlite3.Row:
        found: sqlite3.Row | None = self.conn.execute('SELECT * FROM drafts WHERE id = ?', (draft_id,)).fetchone()
        if found is None:
            raise UnknownDraft(f'no draft with id {draft_id}')
        return found

    def fields(self, draft_id: int) -> Fields:
        loaded: Fields = json.loads(self.row(draft_id)['fields_json'])
        return loaded

    def hash(self, draft_id: int) -> str:
        return content_hash(self.fields(draft_id))

    def change(
        self,
        actor: str,
        action: str,
        sql: str,
        params: Sequence[object],
        draft_id: int | None = None,
        reason_code: str = '',
    ) -> int:
        """THE way state changes: the state write and its 'ok' audit row share one transaction."""
        with self.write() as conn:
            before = None if draft_id is None else self.hash(draft_id)
            cursor = conn.execute(sql, params)
            if draft_id is None:
                assert cursor.lastrowid is not None
                draft_id = cursor.lastrowid
            elif cursor.rowcount != 1:
                raise UnknownDraft(f'no draft with id {draft_id}')
            audit.insert(conn, actor, action, 'ok', draft_id, reason_code, before, self.hash(draft_id))
        return draft_id

    def refuse(self, draft_id: int, actor: str, action: str, outcome: str, reason_code: str) -> None:
        """Blocked, rejected or failed actions change no state; their audit row gets its own transaction."""
        with self.write() as conn:
            current = self.hash(draft_id)
            audit.insert(conn, actor, action, outcome, draft_id, reason_code, current, current)

    def create_draft(self, name: str, fields: Fields, actor: str) -> int:
        return self.change(
            actor, 'extract', 'INSERT INTO drafts (name, fields_json) VALUES (?, ?)', (name, canonical(fields))
        )

    def audit_rows(self, draft_id: int | None = None) -> list[sqlite3.Row]:
        return audit.rows(self.conn, draft_id)
