"""Failure paths: clear errors and no partial writes."""

import socket
import sqlite3
from pathlib import Path

import pytest

from voice_to_doc import Store, Workflow, export_draft
from voice_to_doc.cli import main
from voice_to_doc.export import ExportFailed
from voice_to_doc.extractors import LLM_KEY_ENV
from voice_to_doc.store import StoreError, UnknownDraft

ROOT = Path(__file__).parents[1]
SAMPLE = ROOT / 'samples' / 'order.txt'
R = 'SYNTHETIC_REVIEWER'


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError('Network forbidden in tests')

    monkeypatch.setattr(socket, 'socket', refuse)


def cli_error(argv: list[str]) -> str:
    with pytest.raises(SystemExit) as raised:
        main(argv)
    return str(raised.value)


def test_missing_database_is_a_clear_error_and_is_not_created(tmp_path: Path) -> None:
    db = tmp_path / 'missing.db'
    for argv in (['show', '1'], ['approve', '1', '--actor', R], ['audit']):
        assert 'database not found' in cli_error(['--db', str(db), *argv])
    assert not db.exists()


@pytest.mark.parametrize('command', [['show', '1'], ['extract', str(SAMPLE)], ['demo']])
def test_corrupt_database_is_a_clear_error_and_untouched(tmp_path: Path, command: list[str]) -> None:
    db = tmp_path / 'corrupt.db'
    db.write_bytes(b'SYNTHETIC not a database\n' * 200)
    before = db.read_bytes()
    assert 'cannot read database' in cli_error(['--db', str(db), *command])
    assert db.read_bytes() == before


def test_newer_schema_version_is_refused_without_writes(tmp_path: Path) -> None:
    db = tmp_path / 'newer.db'
    Store(db).close()
    conn = sqlite3.connect(db)
    conn.execute('PRAGMA user_version = 99')
    conn.close()
    before = db.read_bytes()
    with pytest.raises(StoreError, match='schema version 99'):
        Store(db)
    assert 'schema version 99' in cli_error(['--db', str(db), 'extract', str(SAMPLE)])
    assert db.read_bytes() == before


def test_unknown_draft_id(tmp_path: Path) -> None:
    db = tmp_path / 'state.db'
    store = Store(db)
    with pytest.raises(UnknownDraft):
        Workflow.open(store, 999)
    store.close()
    for argv in (['show', '999'], ['approve', '999', '--actor', R], ['export', '999', '--actor', R]):
        assert 'no draft with id 999' in cli_error(['--db', str(db), *argv])
    store = Store(db)
    assert store.audit_rows() == []


def test_invalid_extractor_output_via_cli_is_a_clear_error(tmp_path: Path) -> None:
    db = tmp_path / 'state.db'
    bad = tmp_path / 'no-header.txt'
    bad.write_text('Note type: order\n', encoding='utf-8')  # no SYNTHETIC header
    assert 'SYNTHETIC header required' in cli_error(['--db', str(db), 'extract', str(bad)])


def test_llm_extractor_without_key_fails_before_any_write_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(LLM_KEY_ENV, raising=False)
    db = tmp_path / 'state.db'
    assert LLM_KEY_ENV in cli_error(['--db', str(db), 'extract', str(SAMPLE), '--extractor', 'llm'])
    assert not db.exists()


def test_export_folder_not_writable(tmp_path: Path) -> None:
    db = tmp_path / 'state.db'
    store = Store(db)
    flow = Workflow(SAMPLE.read_text(encoding='utf-8'), name='order', store=store)
    flow.correct('date', '2026-11-20', R)
    flow.approve(R)
    blocker = tmp_path / 'a-file'
    blocker.write_text('SYNTHETIC placeholder\n', encoding='utf-8')
    with pytest.raises(ExportFailed):
        export_draft(flow, blocker / 'out', R)  # parent is a file: the folder cannot be created
    assert flow.exported_hash is None
    row = store.audit_rows()[-1]
    assert (row['action'], row['outcome'], row['reason_code']) == ('export', 'failed', 'write_failed')
    store.close()
    assert 'Export failed' in cli_error(
        ['--db', str(db), 'export', str(flow.id), '--out', str(blocker / 'out'), '--actor', R]
    )
