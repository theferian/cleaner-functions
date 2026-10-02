from __future__ import annotations

from datetime import datetime


class RunLogger:
    def __init__(self, stream=True):
        self.stream = stream
        self.records: list[dict[str, str]] = []

    def __call__(self, level: str, message: str):
        record = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "level": str(level),
            "message": str(message),
        }
        self.records.append(record)
        if self.stream:
            print(f"[{record['level']}] {record['message']}", flush=True)
