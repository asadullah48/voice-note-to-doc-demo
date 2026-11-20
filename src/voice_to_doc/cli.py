"""Offline SYNTHETIC voice-note workflow. Run from the repository root."""
import argparse
from pathlib import Path

from .audit import AuditLog
from .export import export_approved
from .review import Workflow, review


def run_demo(destination=Path('exports'), interactive=False, samples=Path('samples'), audit_path=None):
    audit = AuditLog(audit_path or Path(destination) / 'audit.jsonl')
    documents = {
        path.stem: Workflow(path.read_text(encoding='utf-8'), name=path.stem, audit=audit)
        for path in sorted(Path(samples).glob('*.txt'))
    }
    print('SYNTHETIC DATA ONLY. Offline transcript-to-document demo.')
    if interactive:
        for flow in documents.values():
            review(flow)
    else:
        for flow in documents.values():
            print(flow.draft(), end='')
        order = documents['order']
        try:
            order.approve()
        except ValueError as error:
            print(error)
        order.correct('date', '2026-11-20')
        order.approve()
        print('SIMULATED REVIEWER: approved')
        order.correct('quantity', '14 pieces')
        print('SIMULATED REVIEWER: corrected quantity,', order.state)
        order.approve()
        print('SIMULATED REVIEWER: re-approved')
    paths = export_approved(documents, Path(destination))
    for path in paths:
        print('Exported approved Markdown:', path)
    print('Review audit log (appended):', audit.path)
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(prog='voice_to_doc', description=__doc__)
    parser.add_argument('--review', action='store_true', help='Review each draft yourself')
    parser.add_argument('--samples', type=Path, default=Path('samples'), help='folder of *.txt transcripts')
    parser.add_argument('--exports', type=Path, default=Path('exports'), help='where approved Markdown is written')
    parser.add_argument('--audit-log', type=Path, help='JSONL review log (default: <exports>/audit.jsonl)')
    args = parser.parse_args(argv)
    run_demo(args.exports, args.review, args.samples, args.audit_log)
