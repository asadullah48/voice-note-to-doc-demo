import socket
from pathlib import Path

import pytest

from voice_to_doc import Workflow
from voice_to_doc.extractors import (
    LLM_KEY_ENV,
    LLMExtractor,
    RuleExtractor,
    check_fields,
)
from voice_to_doc.models import DraftState

SAMPLES = Path(__file__).parents[1] / 'samples'
GOOD = {
    'note type': ['order'],
    'who': ['SYNTHETIC_TEAM_ALPHA'],
    'what': ['Blue sample bags'],
    'quantity': ['12 pieces'],
    'date': ['2026-11-20'],
    'action': ['Send the packing list.'],
}


class FakeExtractor:
    """Stands in for any extractor (e.g. an LLM): canned output, no calls."""

    def __init__(self, output):
        self.output, self.seen = output, []

    def extract(self, text):
        self.seen.append(text)
        return self.output


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('Network forbidden in tests')

    monkeypatch.setattr(socket, 'socket', refuse)


def test_rule_extractor_is_default_and_passes_schema():
    for path in SAMPLES.glob('**/*.txt'):
        text = path.read_text(encoding='utf-8')
        output = RuleExtractor().extract(text)
        assert check_fields(output) == output
        assert Workflow(text)._fields == output


def test_valid_fake_output_drives_a_pending_draft_only():
    fake = FakeExtractor({k: list(v) for k, v in GOOD.items()})
    flow = Workflow('SYNTHETIC\nanything at all\n', extractor=fake)
    assert fake.seen == ['SYNTHETIC\nanything at all\n']
    assert flow.state is DraftState.PENDING and flow.approval is None  # a person still has to approve


def test_fake_output_still_gets_business_flags():
    fake = FakeExtractor({**GOOD, 'date': ['next Friday'], 'quantity': ['about 12 pieces']})
    flow = Workflow('SYNTHETIC\n', extractor=fake)
    assert flow.state is DraftState.FLAGGED
    assert {flag.field for flag in flow.flags} == {'date', 'quantity'}


def test_header_checked_before_extractor_runs():
    fake = FakeExtractor(dict(GOOD))
    with pytest.raises(ValueError, match='SYNTHETIC'):
        Workflow('Note type: order\n', extractor=fake)
    assert fake.seen == []


@pytest.mark.parametrize(
    'output',
    [
        None,
        'who: SYNTHETIC_TEAM_ALPHA',
        ['who'],
        {**GOOD, 'state': ['approved']},  # tries to set review state
        {**GOOD, 'approved': ['yes']},
        {'who': 'SYNTHETIC_TEAM_ALPHA'},  # string, not list
        {'who': [123]},
        {'who': [None]},
        {'who': ['']},
        {'who': ['  ']},
        {'who': ['line one\nline two']},  # multi-line value
        {'who': [['nested']]},
        {'Who': ['x']},
    ],
)
def test_schema_rejects_bad_extractor_output(output):
    with pytest.raises(ValueError):
        check_fields(output)
    with pytest.raises(ValueError):
        Workflow('SYNTHETIC\n', extractor=FakeExtractor(output))


def test_check_fields_strips_and_drops_empty_lists():
    assert check_fields({'who': [' A '], 'what': []}) == {'who': ['A']}


def test_llm_extractor_is_off_without_key():
    with pytest.raises(RuntimeError, match=LLM_KEY_ENV):
        LLMExtractor.from_env(env={})
