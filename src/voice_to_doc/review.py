"""Review workflow over the SQLite store. Every change goes through Store.change (state + audit together)."""

from datetime import UTC, datetime

from .draft import canonical, content_hash, render, validate
from .extract import FIELDS
from .extractors import RuleExtractor, TranscriptExtractor, check_fields
from .models import Approval, DraftState, Fields, Flag, Transcript
from .store import Store


class Workflow:
    """One draft under review. State is derived, never set by hand:
    APPROVED while an approval exists; otherwise FLAGGED if validation flags remain, else PENDING."""

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
        if self.approval is not None:
            return DraftState.APPROVED
        return DraftState.FLAGGED if self.flags else DraftState.PENDING

    def draft(self) -> str:
        return render(self.fields, self.issues)

    def correct(self, field: str, value: str, actor: str) -> None:
        field = field.strip().lower()
        value = value.strip()
        if field not in (*FIELDS, 'note type'):
            self.store.refuse(self.id, actor, 'correct', 'rejected', 'unsupported_field')
            raise ValueError('Use a supported field and a single non-empty line')
        if not value or len(value.splitlines()) != 1:
            self.store.refuse(self.id, actor, 'correct', 'rejected', 'invalid_value')
            raise ValueError('Use a supported field and a single non-empty line')
        new_fields = {**self.fields, field: [value]}
        # Any edit, even to the same value, clears approval: it needs a fresh one.
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
        if self.flags:
            self.store.refuse(self.id, actor, 'approve', 'blocked', 'open_flags')
            raise ValueError('Approval blocked until the review flags are resolved')
        approval = Approval(actor, datetime.now(UTC).isoformat(), self.content_hash)
        self.store.change(
            actor,
            'approve',
            'UPDATE drafts SET approval_actor = ?, approval_ts_utc = ?, approval_hash = ? WHERE id = ?',
            (approval.actor, approval.ts_utc, approval.content_hash, self.id),
            self.id,
        )
        return approval

    def next(self, actor: str) -> None:
        """The reviewer moves on from this draft for now; recorded, content unchanged."""
        self.store.change(
            actor,
            'next',
            'UPDATE drafts SET next_ts_utc = ? WHERE id = ?',
            (datetime.now(UTC).isoformat(), self.id),
            self.id,
        )
