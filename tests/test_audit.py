import contextlib
import io
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from voice_to_doc import Workflow, review
from voice_to_doc.audit import AuditLog
from voice_to_doc.cli import main
from voice_to_doc.models import DraftState

SAMPLES = Path(__file__).parents[1] / 'samples'
ORDER = (SAMPLES / 'order.txt').read_text(encoding='utf-8')  # relative date: starts flagged


def summary(log):
    return [(e['action'], e['result'], e['from_state'], e['to_state']) for e in log.read()]


def test_every_review_action_is_logged(tmp_path):
    log = AuditLog(tmp_path / 'audit.jsonl')
    flow = Workflow(ORDER, name='order', audit=log)
    with pytest.raises(ValueError):
        flow.approve()  # blocked
    flow.correct('date', '2026-11-20')  # flagged -> pending
    flow.approve(reviewer='SYNTHETIC_REVIEWER_ONE')  # pending -> approved
    with pytest.raises(ValueError):
        flow.correct('colour', 'blue')  # rejected edit
    flow.correct('quantity', '14 pieces')  # approved -> pending
    flow.correct('date', 'next Friday')  # pending -> flagged

    assert summary(log) == [
        ('approve', 'blocked', 'flagged', 'flagged'),
        ('correct', 'ok', 'flagged', 'pending'),
        ('approve', 'ok', 'pending', 'approved'),
        ('correct', 'rejected', 'approved', 'approved'),
        ('correct', 'ok', 'approved', 'pending'),
        ('correct', 'ok', 'pending', 'flagged'),
    ]
    events = log.read()
    assert events[0]['flags'] == ['date: use an exact YYYY-MM-DD date']
    assert events[1]['field'] == 'date' and events[1]['value'] == '2026-11-20'
    assert events[2]['reviewer'] == 'SYNTHETIC_REVIEWER_ONE'
    assert {e['document'] for e in events} == {'order'}
    assert all(datetime.fromisoformat(e['time']).tzinfo is not None for e in events)
    # Logged states agree with the workflow's real final state.
    assert events[-1]['to_state'] == flow.state.value == DraftState.FLAGGED


def test_log_is_append_only_across_workflows(tmp_path):
    path = tmp_path / 'audit.jsonl'
    Workflow(ORDER, name='a', audit=AuditLog(path)).correct('date', '2026-11-20')
    before = path.read_text(encoding='utf-8')
    Workflow(ORDER, name='b', audit=AuditLog(path)).correct('date', '2026-11-21')
    after = path.read_text(encoding='utf-8')
    assert after.startswith(before) and len(after.splitlines()) == 2


@pytest.mark.parametrize('action', ['correct', 'approve'])
def test_failed_log_write_leaves_state_unchanged(tmp_path, action):
    flow = Workflow(ORDER, name='order', audit=AuditLog(tmp_path))  # a directory: open() fails
    flow.audit = None
    flow.correct('date', '2026-11-20')
    flow.audit = AuditLog(tmp_path)
    before = (flow.state, flow.draft(), flow.approval)
    with pytest.raises(OSError):
        if action == 'correct':
            flow.correct('quantity', '14 pieces')
        else:
            flow.approve()
    assert (flow.state, flow.draft(), flow.approval) == before


def test_interactive_review_logs_each_command(tmp_path):
    log = AuditLog(tmp_path / 'audit.jsonl')
    flow = Workflow(ORDER, name='order', audit=log)
    commands = ['approve', 'date: 2026-11-20', 'approve', 'next']
    with patch('builtins.input', side_effect=commands), contextlib.redirect_stdout(io.StringIO()):
        review(flow, reviewer='SYNTHETIC_REVIEWER_TWO')
    assert [e['action'] for e in log.read()] == ['approve', 'correct', 'approve', 'next']
    assert {e['reviewer'] for e in log.read()} == {'SYNTHETIC_REVIEWER_TWO'}


def test_review_command_writes_review_log(tmp_path):
    argv = ['review', '--samples', str(SAMPLES), '--out', str(tmp_path), '--actor', 'SYNTHETIC_REVIEWER_ONE']
    with patch('builtins.input', side_effect=['next'] * 4), contextlib.redirect_stdout(io.StringIO()) as output:
        main(argv)
    log = AuditLog(tmp_path / 'audit.jsonl')
    assert [(e['action'], e['reviewer']) for e in log.read()] == [('next', 'SYNTHETIC_REVIEWER_ONE')] * 4
    assert 'Review audit log (appended)' in output.getvalue()
