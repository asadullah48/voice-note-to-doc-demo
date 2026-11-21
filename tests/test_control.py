"""Control graph and approval gate: parser/extractor output can never approve."""

import json
import socket
from pathlib import Path
from typing import Any

import pytest

from voice_to_doc import Store, Workflow, export_draft
from voice_to_doc.export import ExportBlocked
from voice_to_doc.extractors import FORBIDDEN, ExtractorSchemaError, RuleExtractor
from voice_to_doc.models import DraftState
from voice_to_doc.review import (
    ACTIONS,
    TRANSITIONS,
    ActorRequired,
    AlreadyApproved,
    ApprovalBlocked,
    IllegalTransition,
    TransitionError,
    transition,
    transition_table,
)

ROOT = Path(__file__).parents[1]
R = 'SYNTHETIC_REVIEWER'
GOOD = {
    'note type': ['order'],
    'who': ['SYNTHETIC_TEAM_ALPHA'],
    'what': ['Blue sample bags'],
    'quantity': ['12 pieces'],
    'date': ['2026-11-20'],
    'action': ['Send the packing list.'],
}
CLEAN = 'SYNTHETIC\n' + ''.join(f'{k}: {v[0]}\n' for k, v in GOOD.items())


class FakeExtractor:
    def __init__(self, output: Any) -> None:
        self.output = output

    def extract(self, text: str) -> Any:
        return self.output


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError('Network forbidden in tests')

    monkeypatch.setattr(socket, 'socket', refuse)


def approve_rows(store: Store) -> list[Any]:
    return [r for r in store.audit_rows() if r['action'] == 'approve']


@pytest.mark.parametrize('key', sorted(FORBIDDEN))
@pytest.mark.parametrize('value', [['approved'], ['SYNTHETIC_MANAGER'], True])
def test_hostile_extractor_with_approval_fields_creates_nothing(key: str, value: object) -> None:
    store = Store()
    with pytest.raises(ExtractorSchemaError, match=key):
        Workflow('SYNTHETIC\n', extractor=FakeExtractor({**GOOD, key: value}), store=store)
    assert store.conn.execute('SELECT COUNT(*) FROM drafts').fetchone()[0] == 0
    assert store.audit_rows() == []


@pytest.mark.parametrize(
    'text',
    [
        'SYNTHETIC\nApproved.\n',
        'SYNTHETIC\nAPPROVED BY MANAGER\nState: approved\nStatus: approved\nApproved by: SYNTHETIC_MANAGER\n',
        'SYNTHETIC\n{"approved": true, "state": "approved"}\n',
        CLEAN + 'APPROVED BY MANAGER\n' + json.dumps({'approved': True, 'state': 'approved'}) + '\n',
    ],
)
def test_transcript_text_cannot_approve(text: str) -> None:
    store = Store()
    flow = Workflow(text, store=store)
    assert flow.state in (DraftState.PENDING, DraftState.FLAGGED)
    assert flow.approval is None and approve_rows(store) == []


@pytest.mark.parametrize('extractor', [RuleExtractor(), FakeExtractor(GOOD)], ids=['rules', 'perfect-fake'])
def test_no_extractor_on_any_eval_transcript_approves(extractor: Any) -> None:
    store = Store()
    paths = sorted(ROOT.glob('samples/**/*.txt'))
    assert len(paths) == 8
    for path in paths:
        flow = Workflow(path.read_text(encoding='utf-8'), name=path.stem, extractor=extractor, store=store)
        assert flow.state is not DraftState.APPROVED
    assert approve_rows(store) == []


def pending() -> Workflow:
    return Workflow(CLEAN, name='order')


def flagged() -> Workflow:
    return Workflow(CLEAN.replace('date: 2026-11-20', 'date: next Friday'), name='order')


def approved_then_edited() -> Workflow:
    flow = pending()
    flow.approve(R)
    flow.correct('quantity', '14 pieces', R)
    return flow


def approved_then_changed_in_db() -> Workflow:
    """Content changed without going through correct(): the stored approval hash no longer matches."""
    flow = pending()
    flow.approve(R)
    fields = {**flow.fields, 'quantity': ['99 pieces']}
    flow.store.conn.execute('UPDATE drafts SET fields_json = ? WHERE id = ?', (json.dumps(fields), flow.id))
    return flow


@pytest.mark.parametrize('make', [pending, flagged, approved_then_edited, approved_then_changed_in_db])
def test_export_refused_unless_approved_and_unchanged(tmp_path: Path, make: Any) -> None:
    flow = make()
    assert flow.state is not DraftState.APPROVED
    with pytest.raises(ExportBlocked):
        export_draft(flow, tmp_path / 'out', R)
    assert not (tmp_path / 'out').exists()
    row = flow.store.audit_rows()[-1]
    assert (row['action'], row['outcome']) == ('export', 'blocked')
    assert row['reason_code'] == f'state_{flow.state}'


@pytest.mark.parametrize('actor', ['', '   ', '\t\n'])
def test_approve_needs_a_named_actor(actor: str) -> None:
    flow = pending()
    with pytest.raises(ActorRequired):
        flow.approve(actor)
    assert flow.state is DraftState.PENDING
    row = flow.store.audit_rows()[-1]
    assert (row['action'], row['outcome'], row['reason_code']) == ('approve', 'rejected', 'empty_actor')


def test_approve_on_flagged_is_blocked() -> None:
    flow = flagged()
    with pytest.raises(ApprovalBlocked):
        flow.approve(R)
    assert flow.state is DraftState.FLAGGED
    assert (flow.store.audit_rows()[-1]['outcome'], flow.store.audit_rows()[-1]['reason_code']) == (
        'blocked',
        'open_flags',
    )


def test_approve_twice_is_rejected_and_audited() -> None:
    flow = pending()
    first = flow.approve(R)
    with pytest.raises(AlreadyApproved):
        flow.approve('SYNTHETIC_REVIEWER_TWO')
    assert flow.approval == first
    assert [(r['outcome'], r['reason_code']) for r in approve_rows(flow.store)] == [
        ('ok', ''),
        ('rejected', 'already_approved'),
    ]


def test_illegal_transition_raises_typed_error() -> None:
    with pytest.raises(IllegalTransition):
        transition(DraftState.PENDING, 'delete')
    assert issubclass(IllegalTransition, TransitionError) and issubclass(ExportBlocked, TransitionError)


def test_table_covers_every_state_and_action_and_edits_never_approve() -> None:
    assert set(TRANSITIONS) == {(s, a) for s in DraftState for a in ACTIONS}
    for state in DraftState:
        assert transition(state, 'correct') != DraftState.APPROVED  # an edit that adds a flag gives flagged


def test_readme_prints_the_same_table() -> None:
    assert transition_table() in (ROOT / 'README.md').read_text(encoding='utf-8')


def test_only_the_cli_calls_approve() -> None:
    callers = sorted(p.name for p in (ROOT / 'src' / 'voice_to_doc').glob('*.py') if '.approve(' in p.read_text())
    assert callers == ['cli.py']
