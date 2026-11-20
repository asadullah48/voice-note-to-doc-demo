"""Score rule-based extraction against the hand-annotated SYNTHETIC eval set."""
import json
from pathlib import Path

import pytest

from voice_to_doc import parse_fields

SAMPLES = Path(__file__).parents[1] / 'samples'
BASELINE = SAMPLES / 'eval' / 'baseline.json'
FIELD_MAP = {'people': 'who', 'quantities': 'quantity', 'dates': 'date', 'actions': 'action'}


def normalise(value):
    value = value.strip()
    if value.endswith(' (uncertain)'):
        value = value[:-len(' (uncertain)')]
    return value.strip().rstrip('.').casefold()


def score(pairs):
    """pairs: iterable of (predicted_fields, expected). Returns {field: {tp, fp, fn}} micro-summed."""
    counts = {name: {'tp': 0, 'fp': 0, 'fn': 0} for name in FIELD_MAP}
    for predicted, expected in pairs:
        for name, field in FIELD_MAP.items():
            got = {normalise(v) for v in predicted.get(field, [])}
            want = {normalise(v) for v in expected[name]}
            counts[name]['tp'] += len(got & want)
            counts[name]['fp'] += len(got - want)
            counts[name]['fn'] += len(want - got)
    return counts


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def eval_pairs():
    for expected_path in sorted(SAMPLES.glob('**/*.expected.json')):
        transcript = expected_path.with_name(expected_path.name.replace('.expected.json', '.txt'))
        yield parse_fields(transcript.read_text(encoding='utf-8')), json.loads(expected_path.read_text(encoding='utf-8'))


def test_scorer_on_known_cases():
    counts = score([({'who': ['A'], 'date': ['kal (uncertain)', 'x']},
                     {'people': ['a'], 'quantities': ['1 box'], 'dates': ['Kal.'], 'actions': []})])
    assert counts['people'] == {'tp': 1, 'fp': 0, 'fn': 0}
    assert counts['dates'] == {'tp': 1, 'fp': 1, 'fn': 0}
    assert counts['quantities'] == {'tp': 0, 'fp': 0, 'fn': 1}
    assert ratio(0, 0) is None


def test_every_eval_transcript_has_expectations():
    transcripts = {p.stem for p in SAMPLES.glob('**/*.txt')}
    expected = {p.name.replace('.expected.json', '') for p in SAMPLES.glob('**/*.expected.json')}
    assert transcripts == expected and len(transcripts) == 8


def test_extraction_eval(capsys):
    counts = score(eval_pairs())
    with capsys.disabled():
        print('\nExtraction eval (8 SYNTHETIC transcripts, micro-averaged)')
        print(f'{"field":<11}{"tp":>4}{"fp":>4}{"fn":>4}{"precision":>11}{"recall":>8}')
        for name, c in counts.items():
            p, r = ratio(c['tp'], c['tp'] + c['fp']), ratio(c['tp'], c['tp'] + c['fn'])
            print(f'{name:<11}{c["tp"]:>4}{c["fp"]:>4}{c["fn"]:>4}'
                  f'{"n/a" if p is None else f"{p:.2f}":>11}{"n/a" if r is None else f"{r:.2f}":>8}')
    if not BASELINE.exists():
        pytest.skip('no baseline recorded yet')
    baseline = json.loads(BASELINE.read_text(encoding='utf-8'))
    for name, c in counts.items():  # ratchet: never fewer hits, never more false positives
        assert c['tp'] >= baseline[name]['tp'], name
        assert c['fp'] <= baseline[name]['fp'], name
