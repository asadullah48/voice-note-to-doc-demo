import dataclasses
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from voice_to_doc import Workflow, export_approved
from voice_to_doc.models import Approval, Draft, DraftState, Flag, Transcript

CLEAN = """SYNTHETIC
Note type: order
Caller: SYNTHETIC_TEAM_ALPHA
Order: Blue sample bags
Qty: 12 pieces
Tareekh: 2026-11-20
Action: Send the packing list.
"""
FLAGGED = 'SYNTHETIC\nNote type: order\nWho: TBD\n'


def approved_flow():
    flow = Workflow(CLEAN, name='order')
    flow.approve()
    assert flow.state is DraftState.APPROVED
    return flow


def test_states_are_explicit():
    assert [s.value for s in DraftState] == ['pending', 'flagged', 'approved']
    assert Workflow(CLEAN).state is DraftState.PENDING
    assert Workflow(FLAGGED).state is DraftState.FLAGGED


def test_approve_records_typed_approval():
    flow = Workflow(CLEAN, name='order')
    approval = flow.approve(reviewer='SYNTHETIC_REVIEWER_ONE')
    assert isinstance(approval, Approval) and flow.approval is approval
    assert approval.reviewer == 'SYNTHETIC_REVIEWER_ONE'
    assert datetime.fromisoformat(approval.approved_at).tzinfo is not None
    assert isinstance(approval.draft, Draft)
    assert approval.draft.state is DraftState.APPROVED
    assert approval.draft.markdown == flow.draft() and approval.draft.flags == ()


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('quantity', '14 pieces'),
        ('quantity', '12 pieces'),  # same value: still an edit, still needs re-approval
        ('what', 'Green sample bags'),
        ('action', 'Call the review team.'),
    ],
)
def test_editing_approved_draft_returns_it_to_pending(field, value):
    flow = approved_flow()
    flow.correct(field, value)
    assert flow.state is DraftState.PENDING
    assert flow.approval is None
    with TemporaryDirectory() as folder:
        assert export_approved({'order': flow}, Path(folder)) == []


def test_edit_that_adds_a_flag_lands_in_flagged_not_approved():
    flow = approved_flow()
    flow.correct('date', 'next Friday')  # invalid date creates a flag
    assert flow.state is DraftState.FLAGGED and flow.approval is None


def test_rejected_edit_keeps_approval():
    flow = approved_flow()
    with pytest.raises(ValueError):
        flow.correct('colour', 'blue')  # unsupported field: nothing changed
    assert flow.state is DraftState.APPROVED


def test_flagged_draft_cannot_be_approved():
    flow = Workflow(FLAGGED)
    with pytest.raises(ValueError, match='Approval blocked'):
        flow.approve()
    assert flow.state is DraftState.FLAGGED and flow.approval is None


def test_flags_are_typed_and_keep_their_text():
    flow = Workflow(FLAGGED)
    assert all(isinstance(flag, Flag) for flag in flow.flags)
    assert Flag('who', 'unclear') in flow.flags
    assert 'who: unclear' in flow.issues


def test_transcript_requires_synthetic_header():
    with pytest.raises(ValueError, match='SYNTHETIC'):
        Transcript('x', 'Note type: order\n')


@pytest.mark.parametrize(
    ('record', 'attr'), [(Transcript('t', 'SYNTHETIC\n'), 'text'), (Flag('who', 'unclear'), 'message')]
)
def test_records_are_immutable(record, attr):
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(record, attr, 'changed')
