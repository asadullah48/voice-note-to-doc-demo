"""Field extraction from SYNTHETIC transcripts: explicit labels first, then rule-based fallback."""
import re

FIELDS = ('who', 'what', 'quantity', 'date', 'action')
LABELS = {
    'caller': 'who', 'order': 'what', 'topic': 'what', 'qty': 'quantity',
    'delivery': 'date', 'tareekh': 'date', 'agla kaam': 'action',
}

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
