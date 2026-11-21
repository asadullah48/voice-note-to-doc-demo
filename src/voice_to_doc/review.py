"""Review control graph over the SQLite store. Every change goes through Store.change (state + audit together)."""

from datetime import UTC, datetime
from typing import Literal

from .draft import canonical, content_hash, render, validate
from .extract import FIELDS
from .extractors import RuleExtractor, TranscriptExtractor, check_fields
from .models import Approval, DraftState, Fields, Flag, Transcript
from .store import Store


class TransitionError(ValueError):
    """An action that the transition table does not allow from the current state."""


class IllegalTransition(TransitionError):
    pass


class ApprovalBlocked(TransitionError):
    pass


class AlreadyApproved(TransitionError):
    pass


class ExportBlocked(TransitionError):
    """Only approved drafts export."""


class ActorRequired(ValueError):
    """Human actions need a non-empty name."""


PENDING, FLAGGED, APPROVED = DraftState.PENDING, DraftState.FLAGGED, DraftState.APPROVED
REVALIDATE: Literal['pending or flagged'] = 'pending or flagged'  # by the new content's flags, never approved
Target = DraftState | Literal['pending or flagged'] | type[TransitionError]
ACTIONS = ('correct', 'approve', 'next', 'export')

# The control graph. States are derived from stored data (see Workflow.state), never set by hand.
TRANSITIONS: dict[tuple[DraftState, str], Target] = {
    (PENDING, 'correct'): REVALIDATE,
    (FLAGGED, 'correct'): REVALIDATE,
    (APPROVED, 'correct'): REVALIDATE,  # any edit drops approval; an edit that adds a flag gives flagged
    (PENDING, 'approve'): APPROVED,
    (FLAGGED, 'approve'): ApprovalBlocked,
    (APPROVED, 'approve'): AlreadyApproved,
    (PENDING, 'next'): PENDING,
    (FLAGGED, 'next'): FLAGGED,
    (APPROVED, 'next'): APPROVED,
    (PENDING, 'export'): ExportBlocked,
    (FLAGGED, 'export'): ExportBlocked,
    (APPROVED, 'export'): APPROVED,  # records the exported hash; state unchanged
}


def transition(state: DraftState, action: str) -> DraftState | Literal['pending or flagged']:
    target = TRANSITIONS.get((state, action))
    if target is None:
        raise IllegalTransition(f'no transition for {action!r} from {state}')
    if isinstance(target, type):
        raise target(f'{action} is not allowed on a {state} draft')
    return target


def transition_table() -> str:
    """The same table as Markdown; README.md must contain it (tested)."""
    lines = ['| state \\ action | ' + ' | '.join(ACTIONS) + ' |', '|---' * (len(ACTIONS) + 1) + '|']
    for state in DraftState:
        cells = []
        for action in ACTIONS:
            target = TRANSITIONS[(state, action)]
            cells.append(f'`{target.__name__}`' if isinstance(target, type) else str(target))
        lines.append(f'| {state} | ' + ' | '.join(cells) + ' |')
    return '\n'.join(lines)


class Workflow:
    """One draft under review. APPROVED only while the stored approval hash equals the current
    content hash AND no flags are open; otherwise FLAGGED if flags remain, else PENDING."""

    def __init__(
        self,
        transcript: Transcript | str,
        name: str = 'draft',
        extractor: TranscriptExtractor | None = None,
        store: Store | None = None,
    ) -> None:
        transcript = transcript if isinstance(transcript, Transcript) else Transcript(name, transcript)
        chosen = extractor or RuleExtractor()
        fields = check_fields(chosen.extract(transcript.text))  # untrusted until this passes; no draft before it
        self.store = store or Store()
        self.id = self.store.create_draft(transcript.name, fields, actor=f'extractor:{type(chosen).__name__}')

    @classmethod
    def open(cls, store: Store, draft_id: int) -> 'Workflow':
        store.row(draft_id)  # raises UnknownDraft
        flow = cls.__new__(cls)
        flow.store, flow.id = store, draft_id
        return flow

    @property
    def name(self) -> str:
        name: str = self.store.row(self.id)['name']
        return name

    @property
    def fields(self) -> Fields:
        return self.store.fields(self.id)

    @property
    def content_hash(self) -> str:
        return content_hash(self.fields)

    @property
    def flags(self) -> list[Flag]:
        return validate(self.fields)

    @property
    def issues(self) -> list[str]:
        return [str(flag) for flag in self.flags]

    @property
    def approval(self) -> Approval | None:
        row = self.store.row(self.id)
        if row['approval_hash'] is None:
            return None
        return Approval(row['approval_actor'], row['approval_ts_utc'], row['approval_hash'])

    @property
    def exported_hash(self) -> str | None:
        exported: str | None = self.store.row(self.id)['exported_hash']
        return exported

    @property
    def state(self) -> DraftState:
        flags = self.flags
        approval = self.approval
        if approval is not None and approval.content_hash == self.content_hash and not flags:
            return APPROVED
        return FLAGGED if flags else PENDING

    def draft(self) -> str:
        return render(self.fields, self.issues)

    def check(self, action: str, actor: str) -> None:
        """Refuse (and audit) a human action the actor or the transition table does not allow."""
        if not actor.strip():
            self.store.refuse(self.id, actor, action, 'rejected', 'empty_actor')
            raise ActorRequired(f'{action} needs a non-empty --actor name')
        try:
            transition(self.state, action)
        except ApprovalBlocked:
            self.store.refuse(self.id, actor, action, 'blocked', 'open_flags')
            raise ApprovalBlocked('Approval blocked until the review flags are resolved') from None
        except AlreadyApproved:
            self.store.refuse(self.id, actor, action, 'rejected', 'already_approved')
            raise
        except ExportBlocked:
            self.store.refuse(self.id, actor, action, 'blocked', f'state_{self.state}')
            raise ExportBlocked(
                f'Export refused: draft {self.id} is {self.state}, only approved drafts export'
            ) from None

    def correct(self, field: str, value: str, actor: str) -> None:
        self.check('correct', actor)
        field = field.strip().lower()
        value = value.strip()
        if field not in (*FIELDS, 'note type'):
            self.store.refuse(self.id, actor, 'correct', 'rejected', 'unsupported_field')
            raise ValueError('Use a supported field and a single non-empty line')
        if not value or len(value.splitlines()) != 1:
            self.store.refuse(self.id, actor, 'correct', 'rejected', 'invalid_value')
            raise ValueError('Use a supported field and a single non-empty line')
        new_fields = {**self.fields, field: [value]}
        # Any edit, even to the same value, also clears the stored approval.
        self.store.change(
            actor,
            'correct',
            'UPDATE drafts SET fields_json = ?, approval_actor = NULL, approval_ts_utc = NULL, approval_hash = NULL'
            ' WHERE id = ?',
            (canonical(new_fields), self.id),
            self.id,
            f'changed:{field}',
        )

    def approve(self, actor: str) -> Approval:
        """The only place an Approval is created. Only the CLI `approve` command calls it."""
        self.check('approve', actor)
        approval = Approval(actor.strip(), datetime.now(UTC).isoformat(), self.content_hash)
        self.store.change(
            approval.actor,
            'approve',
            'UPDATE drafts SET approval_actor = ?, approval_ts_utc = ?, approval_hash = ? WHERE id = ?',
            (approval.actor, approval.ts_utc, approval.content_hash, self.id),
            self.id,
        )
        return approval

    def next(self, actor: str) -> None:
        """The reviewer moves on from this draft for now; recorded, content unchanged."""
        self.check('next', actor)
        self.store.change(
            actor,
            'next',
            'UPDATE drafts SET next_ts_utc = ? WHERE id = ?',
            (datetime.now(UTC).isoformat(), self.id),
            self.id,
        )
