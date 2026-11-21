"""Append-only JSONL log of review actions."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def record(self, **event: Any) -> None:
        """Append one line. Raises on I/O failure so the caller can refuse the action."""
        line = {'time': datetime.now(UTC).isoformat(), **event}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'a', encoding='utf-8') as log:
            log.write(json.dumps(line, sort_keys=True) + '\n')

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines()]
