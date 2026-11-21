"""State and audit live in one SQLite file and commit together or not at all."""

import os
import sqlite3
from pathlib import Path

import pytest

from voice_to_doc import audit
from voice_to_doc.export import ExportFailed, export_draft
from voice_to_doc.review import Workflow
from voice_to_doc.store import Store

R = 'SYNTHETIC_REVIEWER'
CLEAN = (
    (Path(__file__).parents[1] / 'samples' / 'order.txt')
    .read_text(encoding='utf-8')
    .replace('Delivery: next Friday', 'Delivery: 2026-11-20')
)  # no flags: pending
FLAGGED = (Path(__file__).parents[1] / 'samples' / 'order.txt').read_text(encoding='utf-8')  # relative date


def snapshot(path: Path) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    """Read through a fresh connection, so only committed data counts."""
    conn = sqlite3.connect(path)
    try:
        drafts = [tuple(r) for r in conn.execute('SELECT * FROM drafts ORDER BY id')]
        rows = [tuple(r) for r in conn.execute('SELECT * FROM audit ORDER BY id')]
    finally:
        conn.close()
    return drafts, rows


def fresh(tmp_path: Path, text: str = CLEAN) -> tuple[Store, Workflow, Path]:
    path = tmp_path / 'state.db'
    store = Store(path)
    return store, Workflow(text, name='order', store=store), path


def test_failure_after_state_write_before_commit_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, flow, path = fresh(tmp_path)
    before = snapshot(path)
    real_insert = audit.insert

    def insert_then_crash(*args: object, **kwargs: object) -> None:
        real_insert(*args, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError('injected crash before commit')

    monkeypatch.setattr(audit, 'insert', insert_then_crash)
    with pytest.raises(RuntimeError, match='injected'):
        flow.correct('quantity', '14 pieces', R)
    with pytest.raises(RuntimeError, match='injected'):
        flow.approve(R)
    assert snapshot(path) == before


def test_failed_audit_insert_leaves_state_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, flow, path = fresh(tmp_path)
    before = snapshot(path)

    def broken_insert(*args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError('injected audit failure')

    monkeypatch.setattr(audit, 'insert', broken_insert)
    for act in (lambda: flow.correct('quantity', '14 pieces', R), lambda: flow.approve(R), lambda: flow.next(R)):
        with pytest.raises(sqlite3.OperationalError):
            act()
    assert snapshot(path) == before
    assert flow.fields['quantity'] == ['12 pieces'] and flow.approval is None


@pytest.mark.parametrize('sql', ["UPDATE audit SET outcome = 'ok'", 'DELETE FROM audit'])
def test_audit_table_is_append_only(tmp_path: Path, sql: str) -> None:
    store, flow, path = fresh(tmp_path)
    with pytest.raises(sqlite3.DatabaseError, match='append-only'):
        store.conn.execute(sql)
    conn = sqlite3.connect(path)
    with pytest.raises(sqlite3.DatabaseError, match='append-only'):
        conn.execute(sql)
    conn.close()


def test_ok_audit_rows_match_state_changes_and_chain(tmp_path: Path) -> None:
    store, flow, path = fresh(tmp_path)
    flow.correct('quantity', '14 pieces', R)
    flow.approve(R)
    flow.correct('what', 'Green sample bags', R)
    flow.approve(R)
    flow.next(R)
    export_draft(flow, tmp_path / 'out', R)
    ok = [r for r in store.audit_rows() if r['outcome'] == 'ok']
    assert [r['action'] for r in ok] == ['extract', 'correct', 'approve', 'correct', 'approve', 'next', 'export']
    assert ok[0]['before_hash'] is None
    for previous, row in zip(ok, ok[1:], strict=False):  # each change starts where the last one ended
        assert row['before_hash'] == previous['after_hash']
    assert ok[-1]['after_hash'] == flow.content_hash


def test_audit_stores_field_names_and_hashes_not_values(tmp_path: Path) -> None:
    store, flow, path = fresh(tmp_path)
    flow.correct('what', 'SYNTHETIC_UNIQUE_VALUE_42', R)
    row = store.audit_rows()[-1]
    assert row['reason_code'] == 'changed:what'
    assert len(row['after_hash']) == 64 and row['after_hash'] != row['before_hash']
    dump = '\n'.join(str(tuple(r)) for r in store.audit_rows())
    assert 'SYNTHETIC_UNIQUE_VALUE_42' not in dump and 'Blue sample bags' not in dump


def test_blocked_approve_writes_blocked_row_and_changes_nothing(tmp_path: Path) -> None:
    store, flow, path = fresh(tmp_path, FLAGGED)
    drafts_before, rows_before = snapshot(path)
    with pytest.raises(ValueError, match='blocked'):
        flow.approve(R)
    drafts_after, rows_after = snapshot(path)
    assert drafts_after == drafts_before
    assert len(rows_after) == len(rows_before) + 1
    row = store.audit_rows()[-1]
    assert (row['action'], row['outcome'], row['reason_code']) == ('approve', 'blocked', 'open_flags')
    assert row['before_hash'] == row['after_hash'] == flow.content_hash


def test_export_failure_before_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, flow, path = fresh(tmp_path)
    flow.approve(R)
    out = tmp_path / 'out'

    def broken_replace(*args: object) -> None:
        raise OSError('injected replace failure')

    monkeypatch.setattr(os, 'replace', broken_replace)
    with pytest.raises(ExportFailed):
        export_draft(flow, out, R)
    assert list(out.iterdir()) == []  # temp file removed, no final file
    assert flow.exported_hash is None
    row = store.audit_rows()[-1]
    assert (row['action'], row['outcome'], row['reason_code']) == ('export', 'failed', 'write_failed')


def test_export_failure_after_replace_leaves_orphan_file_but_no_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, flow, path = fresh(tmp_path)
    flow.approve(R)
    out = tmp_path / 'out'
    rows_before = snapshot(path)[1]

    def broken_insert(*args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError('injected audit failure')

    monkeypatch.setattr(audit, 'insert', broken_insert)
    with pytest.raises(sqlite3.OperationalError):
        export_draft(flow, out, R)
    files = list(out.iterdir())
    assert [f.name for f in files] == [f'order-{flow.content_hash[:12]}.md']  # orphan file, documented in Limits
    assert flow.exported_hash is None
    assert snapshot(path)[1] == rows_before  # the audit never claims the export happened


def test_export_writes_hash_named_file_and_records_it(tmp_path: Path) -> None:
    store, flow, path = fresh(tmp_path)
    flow.approve(R)
    final = export_draft(flow, tmp_path / 'out', R)
    assert final.name == f'order-{flow.content_hash[:12]}.md'
    assert '**SYNTHETIC**' in final.read_text(encoding='utf-8')
    assert flow.exported_hash == flow.content_hash
    assert [p.name for p in final.parent.iterdir()] == [final.name]  # no temp file left
