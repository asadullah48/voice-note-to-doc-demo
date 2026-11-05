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


SYNTHETIC_NAMES = ('SYNTHETIC_PERSON_ALPHA', 'SYNTHETIC_PERSON_BETA')
UNITS = r'pieces|units|boxes|dozen|than'
QUANTITY = re.compile(
    rf'(?<![\w.,+-])(?:(?:about|around|maybe|roughly|taqreeban)\s+)?'
    rf'[+-]?[0-9]+(?:[.,/-][0-9]+)*(?:\s+to\s+[0-9]+)?\s+(?:{UNITS})\b',
    re.IGNORECASE,
)
DATE = re.compile(
    r'\b(?:[0-9]{4}-[0-9]{2}-[0-9]{2}|'
    r'[0-9]{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|'
    r'Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|'
    r'Nov(?:ember)?|Dec(?:ember)?)(?:\s+[0-9]{4})?|'
    r'(?:next\s+)?(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)|'
    r'kal|parson|next\s+week)\b',
    re.IGNORECASE,
)
ACTION = re.compile(r'\b(?:send|call|deliver|bhejna|check)\b', re.IGNORECASE)
UNCERTAIN = re.compile(
    r"\?|\b(?:maybe|perhaps|might|if|not|never|shayed|shayad|agar|nahin|nahi)\b"
    r"|\b(?:don['’]t|cannot|can['’]t)\b",
    re.IGNORECASE,
)
PERSON = re.compile(
    rf'\b(?:to|for|ko)\s+({"|".join(SYNTHETIC_NAMES)})\b', re.IGNORECASE,
)


def extract_unlabeled(lines):
    """Keep source wording and leave unsupported fields unset."""
    fields = {}
    for line in lines:
        for field, pattern in (('quantity', QUANTITY), ('date', DATE), ('who', PERSON)):
            for match in pattern.finditer(line):
                value = match.group(1).upper() if field == 'who' else match.group()
                if UNCERTAIN.search(line):
                    value = f'{value} (uncertain)'
                values = fields.setdefault(field, [])
                if value not in values:
                    values.append(value)
        if ACTION.search(line):
            fields.setdefault('action', []).append(line.strip())
    return fields


def parse_fields(transcript):
    """Prefer explicit labels and fill unlabeled fields from remaining lines."""
    marker, _, body = transcript.partition('\n')
    if marker.strip() != 'SYNTHETIC':
        raise ValueError('SYNTHETIC header required')
    fields = {}
    unlabeled = []
    for line in body.splitlines():
        label, separator, value = line.partition(':')
        label = label.strip().lower()
        field = LABELS.get(label, label)
        if separator and field in (*FIELDS, 'note type'):
            fields.setdefault(field, [])
            if value.strip():
                fields[field].append(value.strip())
        else:
            unlabeled.append(line)
    for field, values in extract_unlabeled(unlabeled).items():
        fields.setdefault(field, values)
    return {field: values for field, values in fields.items() if values}


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
        if field == 'quantity' and not re.fullmatch(rf'[1-9][0-9]*(?:\s+(?:{UNITS}))?', value, re.IGNORECASE):
            issues.append('quantity: confirm a positive whole number, optionally with pieces, units, boxes, dozen or than')
        if field == 'action' and any(UNCERTAIN.search(item) for item in values):
            issues.append('action: confirm questioned, conditional or negative wording')
        if field == 'who' and value.endswith(' (uncertain)'):
            issues.append('who: confirm the person mentioned in uncertain wording')
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
