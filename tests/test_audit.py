from datetime import datetime
from pathlib import Path

import pytest

from voice_to_doc import Store, Workflow
from voice_to_doc.models import DraftState

SAMPLES = Path(__file__).parents[1] / 'samples'
ORDER = (SAMPLES / 'order.txt').read_text(encoding='utf-8')  # relative date: starts flagged
R = 'SYNTHETIC_REVIEWER'


def summary(store: Store) -> list[tuple[str, str, str]]:
    return [(r['action'], r['outcome'], r['reason_code']) for r in store.audit_rows()]


def test_every_review_action_is_logged() -> None:
    store = Store()
    flow = Workflow(ORDER, name='order', store=store)
    with pytest.raises(ValueError):
        flow.approve(R)  # blocked
    flow.correct('date', '2026-11-20', R)  # flagged -> pending
    flow.approve('SYNTHETIC_REVIEWER_ONE')  # pending -> approved
    with pytest.raises(ValueError):
        flow.correct('colour', 'blue', R)  # rejected edit
    flow.correct('quantity', '14 pieces', R)  # approved -> pending
    flow.correct('date', 'next Friday', R)  # pending -> flagged

    assert summary(store) == [
        ('extract', 'ok', ''),
        ('approve', 'blocked', 'open_flags'),
        ('correct', 'ok', 'changed:date'),
        ('approve', 'ok', ''),
        ('correct', 'rejected', 'unsupported_field'),
        ('correct', 'ok', 'changed:quantity'),
        ('correct', 'ok', 'changed:date'),
    ]
    rows = store.audit_rows()
    assert rows[0]['actor'] == 'extractor:RuleExtractor'
    assert rows[3]['actor'] == 'SYNTHETIC_REVIEWER_ONE'
    assert {r['draft_id'] for r in rows} == {flow.id}
    assert all(datetime.fromisoformat(r['ts_utc']).tzinfo is not None for r in rows)
    assert flow.state is DraftState.FLAGGED


def test_log_is_shared_by_drafts_in_one_file(tmp_path: Path) -> None:
    path = tmp_path / 'state.db'
    first = Store(path)
    Workflow(ORDER, name='a', store=first).correct('date', '2026-11-20', R)
    first.close()
    second = Store(path)
    Workflow(ORDER, name='b', store=second).correct('date', '2026-11-21', R)
    assert [(r['draft_id'], r['action']) for r in second.audit_rows()] == [
        (1, 'extract'),
        (1, 'correct'),
        (2, 'extract'),
        (2, 'correct'),
    ]
