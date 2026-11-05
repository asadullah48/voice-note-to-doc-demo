"""Offline SYNTHETIC voice-note workflow. Python standard library only."""
import argparse
from datetime import date
from pathlib import Path
import re
from tempfile import mkdtemp

FIELDS = ('who', 'what', 'quantity', 'date', 'action')
LABELS = {
    'caller': 'who', 'order': 'what', 'topic': 'what', 'qty': 'quantity',
    'delivery': 'date', 'tareekh': 'date', 'agla kaam': 'action',
}
TITLES = {'meeting': 'Meeting note', 'order': 'Order summary'}
ROOT = Path(__file__).resolve().parent


def parse_fields(transcript):
    """Read supported line labels. Repeated actions form a list."""
    marker, _, body = transcript.partition('\n')
    if marker.strip() != 'SYNTHETIC':
        raise ValueError('SYNTHETIC header required')
    fields = {}
    for line in body.splitlines():
        label, separator, value = line.partition(':')
        label = label.strip().lower()
        field = LABELS.get(label, label)
        if separator and field in (*FIELDS, 'note type') and value.strip():
            fields.setdefault(field, []).append(value.strip())
    return fields


def validate(fields):
    kind = fields.get('note type', [])
    required = ('note type', 'who', 'what', 'date', 'action')
    if kind == ['order']:
        required += ('quantity',)
    issues = [f'{field}: missing' for field in required if not fields.get(field)]
    for field, values in fields.items():
        if field != 'action' and len(values) > 1:
            issues.append(f'{field}: multiple values, choose one')
            continue
        value = values[0]
        if field == 'note type' and value not in TITLES:
            issues.append('note type: use meeting or order')
        if field == 'date':
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError
            except ValueError:
                issues.append('date: use an exact YYYY-MM-DD date')
        if field == 'quantity' and not re.fullmatch(r'[1-9][0-9]*(?: (?:pieces|units|boxes))?', value):
            issues.append('quantity: use a positive whole number, optionally with pieces, units or boxes')
        if field in ('who', 'what', 'action') and any(
            item.lower() in {'?', 'tbd', 'unknown', 'unclear', 'not sure'} for item in values
        ):
            issues.append(f'{field}: unclear')
    return issues


class Workflow:
    def __init__(self, transcript):
        self._fields = parse_fields(transcript)
        self._approved = None

    @property
    def issues(self):
        return validate(self._fields)

    @property
    def status(self):
        if self._approved is not None:
            return 'approved'
        return 'waiting_for_details' if self.issues else 'waiting_for_approval'

    def draft(self):
        fields = self._fields
        kind = fields.get('note type', [''])[0]
        lines = [f'# {TITLES.get(kind, "Document draft")}', '', '**SYNTHETIC**', '']
        for field in ('who', 'what', 'date', 'quantity'):
            if field != 'quantity' or kind == 'order' or field in fields:
                value = ' / '.join(fields.get(field, ['Missing']))
                lines.append(f'- **{field.title()}** {value}')
        lines.extend(('', '## Action items', ''))
        lines.extend(f'- {action}' for action in fields.get('action', ['Missing']))
        if self.issues:
            lines.extend(('', '## Review flags', ''))
            lines.extend(f'- {issue}' for issue in self.issues)
        return '\n'.join(lines) + '\n'

    def correct(self, field, value):
        field = field.strip().lower()
        value = value.strip()
        if field not in (*FIELDS, 'note type') or not value or len(value.splitlines()) != 1:
            raise ValueError('Use a supported field and a single non-empty line')
        self._fields[field] = [value]
        self._approved = None

    def approve(self):
        if self.issues:
            raise ValueError('Approval blocked until the review flags are resolved')
        self._approved = self.draft()


def export_approved(documents, destination):
    """Save approved snapshots in a fresh directory for each export."""
    approved = [(name, flow._approved) for name, flow in documents.items() if flow.status == 'approved']
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


def review(flow):
    while True:
        print(flow.draft())
        print('Review status:', flow.status)
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


def run_demo(destination=ROOT / 'exports', interactive=False):
    documents = {
        path.stem: Workflow(path.read_text(encoding='utf-8'))
        for path in sorted((ROOT / 'samples').glob('*.txt'))
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
        print('SIMULATED REVIEWER: corrected quantity,', order.status)
        order.approve()
        print('SIMULATED REVIEWER: re-approved')
    paths = export_approved(documents, destination)
    for path in paths:
        print('Exported approved Markdown:', path)
    return paths


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', action='store_true', help='Review each draft yourself')
    run_demo(interactive=parser.parse_args().review)
