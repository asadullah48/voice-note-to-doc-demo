"""Offline SYNTHETIC voice-note workflow."""

import argparse
from collections.abc import Sequence
from pathlib import Path

from .audit import AuditLog
from .export import export_approved
from .extractors import LLMExtractor, RuleExtractor, TranscriptExtractor
from .review import Workflow, review

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


def run_demo(out: Path) -> None:
    """Extract and review one bundled transcript. Never approves: a person has to."""
    print('SYNTHETIC DATA ONLY. Offline transcript-to-document demo. The demo never approves anything.')
    flow = Workflow(DEMO_TRANSCRIPT, name='demo-order')
    print(flow.draft(), end='')
    print('Flags:', '; '.join(flow.issues) or 'none')
    print('State:', flow.state)
    if not export_approved({flow.name: flow}, out):
        print(f'Export refused: draft is {flow.state}, only approved drafts export.')
    print('To approve and export, a person runs the interactive review on the SYNTHETIC samples:')
    print('  python -m voice_to_doc review --samples samples --actor "<your name>"')


def run_review(samples: Path, out: Path, audit_path: Path, actor: str, extractor: TranscriptExtractor) -> list[Path]:
    audit = AuditLog(audit_path)
    documents = {
        path.stem: Workflow(path.read_text(encoding='utf-8'), name=path.stem, audit=audit, extractor=extractor)
        for path in sorted(samples.glob('*.txt'))
    }
    print('SYNTHETIC DATA ONLY. Offline transcript-to-document review.')
    for flow in documents.values():
        review(flow, actor)
    paths = export_approved(documents, out)
    for path in paths:
        print('Exported approved Markdown:', path)
    print('Review audit log (appended):', audit.path)
    return paths


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog='voice_to_doc', description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    demo = sub.add_parser('demo', help='run the bundled SYNTHETIC example; never approves')
    demo.add_argument('--out', type=Path, default=Path('out'), help='export folder')
    rv = sub.add_parser('review', help='review each sample yourself, then export approved drafts')
    rv.add_argument('--actor', required=True, help='your name, recorded with every action')
    rv.add_argument('--samples', type=Path, default=Path('samples'), help='folder of *.txt transcripts')
    rv.add_argument('--out', type=Path, default=Path('out'), help='where approved Markdown is written')
    rv.add_argument('--audit-log', type=Path, help='JSONL review log (default: <out>/audit.jsonl)')
    rv.add_argument(
        '--extractor',
        choices=('rules', 'llm'),
        default='rules',
        help='llm is opt-in and needs VOICE_TO_DOC_ANTHROPIC_API_KEY',
    )
    args = parser.parse_args(argv)
    if args.command == 'demo':
        run_demo(args.out)
        return
    extractor: TranscriptExtractor = LLMExtractor.from_env() if args.extractor == 'llm' else RuleExtractor()
    run_review(args.samples, args.out, args.audit_log or args.out / 'audit.jsonl', args.actor, extractor)
