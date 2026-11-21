"""Offline SYNTHETIC voice-note workflow. State and audit live in one SQLite file (--db)."""

import argparse
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from .export import export_draft
from .extractors import LLMExtractor, RuleExtractor, TranscriptExtractor
from .review import Workflow
from .store import Store, StoreError, default_db

BANNER = 'SYNTHETIC DATA ONLY. Offline transcript-to-document demo.'
# Bundled so `python -m voice_to_doc demo` works from any folder. Same text as samples/order.txt.
DEMO_TRANSCRIPT = """SYNTHETIC
Note type: order
Caller: SYNTHETIC_TEAM_ALPHA
Order: Blue sample bags
Qty: 12 pieces
Delivery: next Friday
Agla kaam: Check packing before dispatch.
Action: Send the packing list to the review team.
"""


def show(flow: Workflow) -> None:
    print(f'Draft {flow.id} ({flow.name})')
    print(flow.draft(), end='')
    print('Flags:', '; '.join(flow.issues) or 'none')
    print('State:', flow.state)


def run_demo(db: Path, out: Path) -> None:
    """Extract one bundled transcript and try to export it. Never approves: a person has to."""
    print(BANNER, 'The demo never approves anything.')
    store = Store(db)
    try:
        flow = Workflow(DEMO_TRANSCRIPT, name='demo-order', store=store)
        show(flow)
        try:
            export_draft(flow, out, 'voice_to_doc demo')
        except ValueError as error:
            print(error)
        prefix = f'python -m voice_to_doc --db "{db}"'
        print('To approve and export, a person runs (2026-11-20 is an example SYNTHETIC date):')
        print(f'  {prefix} correct {flow.id} date 2026-11-20 --actor "<your name>"')
        print(f'  {prefix} approve {flow.id} --actor "<your name>"')
        print(f'  {prefix} export {flow.id} --out "{out}" --actor "<your name>"')
    finally:
        store.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='voice_to_doc', description=__doc__)
    parser.add_argument('--db', type=Path, default=default_db(), help='SQLite file (env VOICE_TO_DOC_DB)')
    sub = parser.add_subparsers(dest='command', required=True)
    demo = sub.add_parser('demo', help='run the bundled SYNTHETIC example; never approves')
    demo.add_argument('--out', type=Path, default=Path('out'), help='export folder')
    extract = sub.add_parser('extract', help='create a draft from a SYNTHETIC transcript file')
    extract.add_argument('transcript', type=Path)
    extract.add_argument('--name', help='draft name (default: file name)')
    extract.add_argument(
        '--extractor',
        choices=('rules', 'llm'),
        default='rules',
        help='llm is opt-in; needs VOICE_TO_DOC_ANTHROPIC_API_KEY',
    )
    sub.add_parser('show', help='print a draft, its flags and state').add_argument('draft_id', type=int)
    correct = sub.add_parser('correct', help='replace one field value')
    correct.add_argument('draft_id', type=int)
    correct.add_argument('field')
    correct.add_argument('value')
    for name, text in (('approve', 'approve a draft with no open flags'), ('next', 'move on from a draft')):
        sub.add_parser(name, help=text).add_argument('draft_id', type=int)
    export = sub.add_parser('export', help='write an approved draft to Markdown')
    export.add_argument('draft_id', type=int)
    export.add_argument('--out', type=Path, default=Path('out'))
    sub.add_parser('audit', help='print the audit log').add_argument('draft_id', type=int, nargs='?')
    for name in ('correct', 'approve', 'next', 'export'):
        sub.choices[name].add_argument('--actor', required=True, help='your name, recorded in the audit log')
    return parser


def run(args: argparse.Namespace) -> None:
    if args.command == 'demo':
        run_demo(args.db, args.out)
        return
    if args.command == 'extract':  # chosen and read before the DB opens: a missing key or file writes nothing
        extractor: TranscriptExtractor = LLMExtractor.from_env() if args.extractor == 'llm' else RuleExtractor()
        text = args.transcript.read_text(encoding='utf-8')
    store = Store(args.db, create=args.command == 'extract')
    try:
        if args.command == 'extract':
            show(Workflow(text, name=args.name or args.transcript.stem, extractor=extractor, store=store))
        elif args.command == 'audit':
            for row in store.audit_rows(args.draft_id):
                print(*(row[key] for key in row.keys()), sep='\t')
        else:
            flow = Workflow.open(store, args.draft_id)
            if args.command == 'correct':
                flow.correct(args.field, args.value, args.actor)
            elif args.command == 'approve':
                flow.approve(args.actor)
            elif args.command == 'next':
                flow.next(args.actor)
            elif args.command == 'export':
                print('Exported approved Markdown:', export_draft(flow, args.out, args.actor))
            show(flow)
    finally:
        store.close()


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        run(args)
    except (StoreError, ValueError, RuntimeError, OSError, sqlite3.Error) as error:
        raise SystemExit(f'error: {error}') from error
