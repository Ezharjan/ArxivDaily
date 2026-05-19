"""Persisted state — the set of arXiv IDs we've already emailed about.

Stored as a JSON file (state.json) at the repo root and committed back by
the GitHub Action after each successful run. This is what makes the
toolkit only email when arXiv actually has new matching papers.

State layout:
  {
    "version": 1,
    "last_run_utc": "2026-05-17T08:00:00+00:00",
    "last_sent_utc": "2026-05-17T08:00:00+00:00",
    "seen_ids": ["2405.01234", "2405.05678", ...]
  }
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
from dataclasses import dataclass, field
from typing import List, Set

log = logging.getLogger(__name__)

_MAX_SEEN_IDS = 5000  # rolling cap so the file doesn't grow unboundedly


@dataclass
class State:
    version: int = 1
    last_run_utc: str = ""
    last_sent_utc: str = ""
    seen_ids: List[str] = field(default_factory=list)

    @property
    def seen_set(self) -> Set[str]:
        return set(self.seen_ids)

    def mark_seen(self, ids: List[str]) -> None:
        # Preserve insertion order, newest at the front, dedupe, then cap.
        existing = self.seen_set
        new_unique = [i for i in ids if i not in existing]
        self.seen_ids = new_unique + self.seen_ids
        if len(self.seen_ids) > _MAX_SEEN_IDS:
            self.seen_ids = self.seen_ids[:_MAX_SEEN_IDS]

    def to_json(self) -> str:
        return json.dumps(
            {
                "version": self.version,
                "last_run_utc": self.last_run_utc,
                "last_sent_utc": self.last_sent_utc,
                "seen_ids": self.seen_ids,
            },
            indent=2,
        )


def load(path: str) -> State:
    if not os.path.exists(path):
        log.info("no existing state at %s — starting fresh", path)
        return State()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:  # noqa: BLE001
        log.warning("could not parse state file %s (%s) — starting fresh", path, e)
        return State()
    return State(
        version=int(data.get("version", 1)),
        last_run_utc=str(data.get("last_run_utc", "")),
        last_sent_utc=str(data.get("last_sent_utc", "")),
        seen_ids=list(data.get("seen_ids", [])),
    )


def save(path: str, state: State) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(state.to_json())
        f.write("\n")
    os.replace(tmp, path)
    log.info("wrote state to %s (%d ids)", path, len(state.seen_ids))


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
