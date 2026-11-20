"""Review workflow: corrections clear approval; approval is blocked while flags remain."""
from dataclasses import replace
from datetime import UTC, datetime

from .draft import render, validate
from .extract import FIELDS, parse_fields
from .models import Approval, Draft, DraftState, Transcript


class Workflow:
    """One transcript under review. State is derived, never set by hand:
    APPROVED while an approval exists; otherwise FLAGGED if validation flags remain, else PENDING."""

    def __init__(self, transcript, name='draft'):
        self.transcript = transcript if isinstance(transcript, Transcript) else Transcript(name, transcript)
        self.name = self.transcript.name
        self._fields = parse_fields(self.transcript.text)
        self.approval = None

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

    def correct(self, field, value):
        field = field.strip().lower()
        value = value.strip()
        if field not in (*FIELDS, 'note type') or not value or len(value.splitlines()) != 1:
            raise ValueError('Use a supported field and a single non-empty line')
        self._fields[field] = [value]
        self.approval = None  # any edit, even to an approved draft, needs a fresh approval

    def approve(self, reviewer='SYNTHETIC_REVIEWER'):
        if self.flags:
            raise ValueError('Approval blocked until the review flags are resolved')
        snapshot = replace(self.snapshot(), state=DraftState.APPROVED)
        self.approval = Approval(snapshot, reviewer, datetime.now(UTC).isoformat())
        return self.approval


def review(flow):
    while True:
        print(flow.draft())
        print('Review status:', flow.state)
        command = input('Approve, edit (field: value), or next? ').strip()
        try:
            if command == 'next':
                return
            if command == 'approve':
                flow.approve()
            elif ':' in command:
                flow.correct(*command.split(':', 1))
            else:
                print('Enter approve, field: value, or next.')
        except ValueError as error:
            print(error)
