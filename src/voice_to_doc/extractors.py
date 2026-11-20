"""Transcript extractors. Every extractor's output passes check_fields before a draft uses it."""
import json
import os
from typing import Protocol

from .extract import FIELDS, parse_fields

ALLOWED = (*FIELDS, 'note type')
LLM_KEY_ENV = 'VOICE_TO_DOC_ANTHROPIC_API_KEY'  # dedicated name so a global key never turns this on


class TranscriptExtractor(Protocol):
    def extract(self, text: str) -> dict:
        """Return {field: [values]}; untrusted until check_fields passes."""


def check_fields(fields):
    """Shared schema: known fields only, each a list of non-empty single-line strings."""
    if not isinstance(fields, dict):
        raise ValueError('Extractor output must be an object')
    clean = {}
    for key, values in fields.items():
        if key not in ALLOWED:
            raise ValueError(f'Extractor output has unknown field: {key!r}')
        if not isinstance(values, list):
            raise ValueError(f'Extractor field {key!r} must be a list of strings')
        items = []
        for value in values:
            if not isinstance(value, str) or not value.strip() or len(value.strip().splitlines()) != 1:
                raise ValueError(f'Extractor field {key!r} must hold non-empty single-line strings')
            items.append(value.strip())
        if items:
            clean[key] = items
    return clean


class RuleExtractor:
    """Default: explicit labels, then the rule-based fallback."""

    def extract(self, text):
        return parse_fields(text)


class LLMExtractor:
    """Optional extractor via the Anthropic API. OFF by default.

    Needs `pip install -e ".[llm]"`, the VOICE_TO_DOC_ANTHROPIC_API_KEY env var and
    `--extractor llm`. Never executed in this repo's tests or CI; no live call verified.
    """

    SYSTEM = ('Extract fields from the SYNTHETIC voice-note transcript. Reply with only a JSON object. '
              'Allowed keys: ' + ', '.join(ALLOWED) + '. Each value is a list of strings copied from '
              'the transcript wording. Omit anything the transcript does not state. Never add other keys.')

    def __init__(self, api_key, model='claude-opus-5-5'):
        import anthropic  # optional dependency, imported only when this extractor is chosen
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    @classmethod
    def from_env(cls, env=None):
        key = (os.environ if env is None else env).get(LLM_KEY_ENV)
        if not key:
            raise RuntimeError(f'{LLM_KEY_ENV} is not set; the LLM extractor stays off')
        return cls(key)

    def extract(self, text):
        response = self.client.messages.create(
            model=self.model, max_tokens=2048, system=self.SYSTEM,
            messages=[{'role': 'user', 'content': text}])
        if response.stop_reason == 'refusal':
            raise ValueError('LLM extractor declined the transcript')
        reply = ''.join(block.text for block in response.content if block.type == 'text')
        try:
            return json.loads(reply)  # untrusted: Workflow runs check_fields, then validate()
        except json.JSONDecodeError:
            raise ValueError('LLM extractor did not return JSON') from None
