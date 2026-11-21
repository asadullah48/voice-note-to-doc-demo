"""Typed records passed between extract, draft, review and export."""

from dataclasses import dataclass
from enum import StrEnum

Fields = dict[str, list[str]]


class DraftState(StrEnum):
    PENDING = 'pending'  # no flags, waiting for a reviewer
    FLAGGED = 'flagged'  # has review flags; approval is blocked
    APPROVED = 'approved'  # a reviewer approved this exact revision


@dataclass(frozen=True)
class Transcript:
    name: str
    text: str

    def __post_init__(self) -> None:
        if self.text.partition('\n')[0].strip() != 'SYNTHETIC':
            raise ValueError('SYNTHETIC header required')


@dataclass(frozen=True)
class Flag:
    field: str
    message: str

    def __str__(self) -> str:
        return f'{self.field}: {self.message}'


@dataclass(frozen=True)
class Approval:
    """A person's approval of one exact content version. Only review.Workflow.approve creates it."""

    actor: str
    ts_utc: str  # UTC ISO-8601
    content_hash: str  # SHA-256 of the draft content at approval time
