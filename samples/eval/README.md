# SYNTHETIC extraction eval set

Each `<name>.txt` transcript has a hand-written `<name>.expected.json` next to it
(`samples/` for the four demo transcripts, `samples/eval/` for four extra probes).
Expected values were written from what the transcript says, not from extractor output.
The `eval/` probes deliberately include cases the rules are known to miss.

Annotation rules:
- **people**: named people or teams the note is about or addressed to (not the speaker).
- **quantities**: number plus unit as spoken, including spelled-out numbers.
- **dates**: every date or day phrase as spoken (not converted to ISO).
- **actions**: the full sentence (label removed) for something someone should do,
  including tentative or conditional ones. Prohibitions ("do not ...") and past
  events are not actions.

Scoring (`tests/test_eval.py`): per field, matched as sets after trimming, case-folding,
dropping a trailing period and the extractor's ` (uncertain)` suffix. Precision and recall
are micro-averaged over all eight transcripts. Eight short synthetic transcripts are far
too few to estimate real-world accuracy; the numbers only track this rule set on this set.
