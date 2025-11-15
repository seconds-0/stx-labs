"""Helpers for emitting structured ops progress events."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone


EVENT_PREFIX = "OPS_PROGRESS"


@dataclass(frozen=True)
class ProgressEvent:
    task: str
    stage: str
    current: float
    total: float
    detail: str
    timestamp: str

    def to_json(self) -> str:
        payload = {
            "task": self.task,
            "stage": self.stage,
            "current": self.current,
            "total": self.total,
            "detail": self.detail,
            "timestamp": self.timestamp,
        }
        return json.dumps(payload, separators=(",", ":"))


def emit_progress(stage: str, current: float, total: float, detail: str = "") -> None:
    """Print a structured progress event for the active OPS task."""

    task = os.environ.get("OPS_TASK")
    if not task or total <= 0:
        return
    event = ProgressEvent(
        task=task,
        stage=stage,
        current=current,
        total=total,
        detail=detail,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    print(f"{EVENT_PREFIX} {event.to_json()}", file=sys.stdout, flush=True)
