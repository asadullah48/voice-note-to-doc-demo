"""Export one approved draft. The file and the DB row cannot share a transaction, so the order is:
temp file -> fsync -> os.replace to a hash-named final file -> one transaction (exported state + audit row).
A crash between the last two leaves an orphan file and no audit claim that the export happened."""

import os
import tempfile
from pathlib import Path

from .review import ExportBlocked, Workflow

__all__ = ['ExportBlocked', 'ExportFailed', 'export_draft']


class ExportFailed(RuntimeError):
    """The file could not be written; nothing was recorded as exported."""


def export_draft(flow: Workflow, out: Path, actor: str) -> Path:
    flow.check('export', actor)  # refuses and audits unless approved (transition table)
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
