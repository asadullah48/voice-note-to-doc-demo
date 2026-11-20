"""Export approved snapshots only, each run into a fresh folder."""
from pathlib import Path
from tempfile import mkdtemp

from .models import DraftState


def export_approved(documents, destination):
    """Save approved snapshots in a fresh directory for each export."""
    approved = [(name, flow.approval.draft.markdown) for name, flow in documents.items()
                if flow.state is DraftState.APPROVED]
    if not approved:
        return []
    destination.mkdir(parents=True, exist_ok=True)
    run_folder = Path(mkdtemp(prefix='run-', dir=destination))
    paths = []
    for name, markdown in approved:
        path = run_folder / f'{name}.md'
        path.write_text(markdown, encoding='utf-8')
        paths.append(path)
    return paths
