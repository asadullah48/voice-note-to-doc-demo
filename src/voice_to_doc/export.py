"""Export one approved draft. The file and the DB row cannot share a transaction, so the order is:
temp file -> fsync -> os.replace to a hash-named final file -> one transaction (exported state + audit row).
A crash between the last two leaves an orphan file and no audit claim that the export happened."""

import os
import tempfile
from pathlib import Path

from .models import DraftState
from .review import Workflow


class ExportBlocked(ValueError):
    """Only approved drafts export."""


class ExportFailed(RuntimeError):
    """The file could not be written; nothing was recorded as exported."""


def export_draft(flow: Workflow, out: Path, actor: str) -> Path:
    state = flow.state
    if state is not DraftState.APPROVED:
        flow.store.refuse(flow.id, actor, 'export', 'blocked', f'state_{state}')
        raise ExportBlocked(f'Export refused: draft {flow.id} is {state}, only approved drafts export')
    markdown, digest = flow.draft(), flow.content_hash
    final = out / f'{flow.name}-{digest[:12]}.md'
    temp: str | None = None
    try:
        out.mkdir(parents=True, exist_ok=True)
        handle, temp = tempfile.mkstemp(dir=out, prefix='.export-', suffix='.tmp')
        with os.fdopen(handle, 'w', encoding='utf-8') as file:
            file.write(markdown)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, final)
    except OSError as error:
        if temp is not None and os.path.exists(temp):
            os.remove(temp)  # our own temp file, never the final one
        flow.store.refuse(flow.id, actor, 'export', 'failed', 'write_failed')
        raise ExportFailed(f'Export failed, nothing recorded: {error}') from error
    flow.store.change(
        actor,
        'export',
        'UPDATE drafts SET exported_hash = ?, exported_path = ? WHERE id = ?',
        (digest, str(final), flow.id),
        flow.id,
    )
    return final
