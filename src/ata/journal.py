"""Append-only JSONL journal for immutable decision records."""

import json
import os
import threading
from pathlib import Path
from typing import Any

from ata.domain import DecisionRecord


class DecisionJournal:
    """Persist decision records without mutating prior entries."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def append(self, record: DecisionRecord) -> None:
        payload = (
            json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            descriptor = os.open(
                self.path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            try:
                remaining = memoryview(payload)
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written == 0:
                        raise OSError("journal write returned zero bytes")
                    remaining = remaining[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"invalid journal JSON at line {line_number}") from error
                if not isinstance(value, dict):
                    raise ValueError(f"journal entry at line {line_number} must be an object")
                records.append(value)
        return records
