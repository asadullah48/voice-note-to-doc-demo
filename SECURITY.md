# Security policy

This repository is a **demo**. It works on **SYNTHETIC data only** and is not meant for
production use or for real personal data. Do not put real names, phone numbers, emails,
client records or real transcripts into it.

## Reporting

Report issues by email to asadullahshafique@hotmail.com.

## In scope

- The audit log (what it records, and that it never claims an action that did not happen).
- The approval gate (only a named person can approve; extractor output can never approve).
- Export (only approved, unchanged drafts are written).

## Secrets

There are no secrets in this repository. The optional LLM extractor reads its API key
only from the `VOICE_TO_DOC_ANTHROPIC_API_KEY` environment variable and is off by default.
