"""Validation flags and Markdown rendering for a draft."""
import re
from datetime import date

from .extract import UNCERTAIN, UNITS
from .models import Flag

TITLES = {'meeting': 'Meeting note', 'order': 'Order summary'}


def validate(fields):
    """Return a list of Flag; an empty list means the draft can be approved."""
    kind = fields.get('note type', [])
    required = ('note type', 'who', 'what', 'date', 'action')
    if kind == ['order']:
        required += ('quantity',)
    issues = [Flag(field, 'missing') for field in required if not fields.get(field)]
    for field, values in fields.items():
        if field != 'action' and len(values) > 1:
            issues.append(Flag(field, 'multiple values, choose one'))
            continue
        value = values[0]
        if field == 'note type' and value not in TITLES:
            issues.append(Flag('note type', 'use meeting or order'))
        if field == 'date':
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError
            except ValueError:
                issues.append(Flag('date', 'use an exact YYYY-MM-DD date'))
        if field == 'quantity' and not re.fullmatch(rf'[1-9][0-9]*(?:\s+(?:{UNITS}))?', value, re.IGNORECASE):
            issues.append(Flag('quantity', 'confirm a positive whole number, optionally with pieces, units, boxes, dozen or than'))
        if field == 'action' and any(UNCERTAIN.search(item) for item in values):
            issues.append(Flag('action', 'confirm questioned, conditional or negative wording'))
        if field == 'who' and value.endswith(' (uncertain)'):
            issues.append(Flag('who', 'confirm the person mentioned in uncertain wording'))
        if field in ('who', 'what', 'action') and any(
            item.lower() in {'?', 'tbd', 'unknown', 'unclear', 'not sure'} for item in values
        ):
            issues.append(Flag(field, 'unclear'))
    return issues


def render(fields, issues):
    """Markdown for the reviewer; review flags are listed until resolved."""
    kind = fields.get('note type', [''])[0]
    lines = [f'# {TITLES.get(kind, "Document draft")}', '', '**SYNTHETIC**', '']
    for field in ('who', 'what', 'date', 'quantity'):
        if field != 'quantity' or kind == 'order' or field in fields:
            value = ' / '.join(fields.get(field, ['Missing']))
            lines.append(f'- **{field.title()}** {value}')
    lines.extend(('', '## Action items', ''))
    lines.extend(f'- {action}' for action in fields.get('action', ['Missing']))
    if issues:
        lines.extend(('', '## Review flags', ''))
        lines.extend(f'- {issue}' for issue in issues)
    return '\n'.join(lines) + '\n'
