"""Review workflow: corrections clear approval; approval is blocked while flags remain."""
from dataclasses import replace
from datetime import UTC, datetime

from .draft import render, validate
from .extract import FIELDS
from .extractors import RuleExtractor, check_fields
from .models import Approval, Draft, DraftState, Transcript


class Workflow:
    """One transcript under review. State is derived, never set by hand:
    APPROVED while an approval exists; otherwise FLAGGED if validation flags remain, else PENDING."""

    def __init__(self, transcript, name='draft', audit=None, extractor=None):
        self.transcript = transcript if isinstance(transcript, Transcript) else Transcript(name, transcript)
        self.name = self.transcript.name
        self._fields = check_fields((extractor or RuleExtractor()).extract(self.transcript.text))
        self.approval = None
        self.audit = audit  # AuditLog or None

    @property
    def flags(self):
        return validate(self._fields)

    @property
    def issues(self):
        return [str(flag) for flag in self.flags]

    @property
    def state(self):
        if self.approval is not None:
            return DraftState.APPROVED
        return DraftState.FLAGGED if self.flags else DraftState.PENDING

    def draft(self):
        return render(self._fields, self.issues)

    def snapshot(self):
        return Draft(self.name, {k: list(v) for k, v in self._fields.items()},
                     tuple(self.flags), self.state, self.draft())

    def _log(self, action, reviewer, result, to_state, **details):
        # Written before the in-memory change: if the write fails, the action does not happen.
        if self.audit is not None:
            self.audit.record(document=self.name, action=action, reviewer=reviewer, result=result,
                              from_state=self.state.value, to_state=to_state.value, **details)

    def correct(self, field, value, reviewer='SYNTHETIC_REVIEWER'):
        field = field.strip().lower()
        value = value.strip()
        if field not in (*FIELDS, 'note type') or not value or len(value.splitlines()) != 1:
            self._log('correct', reviewer, 'rejected', self.state, field=field)
            raise ValueError('Use a supported field and a single non-empty line')
        new_fields = {**self._fields, field: [value]}
        to_state = DraftState.FLAGGED if validate(new_fields) else DraftState.PENDING
        self._log('correct', reviewer, 'ok', to_state, field=field, value=value)
        self._fields = new_fields
        self.approval = None  # any edit, even to an approved draft, needs a fresh approval

    def approve(self, reviewer='SYNTHETIC_REVIEWER'):
        if self.flags:
            self._log('approve', reviewer, 'blocked', self.state, flags=self.issues)
            raise ValueError('Approval blocked until the review flags are resolved')
        self._log('approve', reviewer, 'ok', DraftState.APPROVED)
        snapshot = replace(self.snapshot(), state=DraftState.APPROVED)
        self.approval = Approval(snapshot, reviewer, datetime.now(UTC).isoformat())
        return self.approval


def review(flow, reviewer='SYNTHETIC_REVIEWER'):
    while True:
        print(flow.draft())
        print('Review status:', flow.state)
        command = input('Approve, edit (field: value), or next? ').strip()
        try:
            if command == 'next':
                flow._log('next', reviewer, 'ok', flow.state)
                return
            if command == 'approve':
                flow.approve(reviewer)
            elif ':' in command:
                flow.correct(*command.split(':', 1), reviewer=reviewer)
            else:
                print('Enter approve, field: value, or next.')
        except ValueError as error:
            print(error)
