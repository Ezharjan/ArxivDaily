"""Persisted state — the set of arXiv IDs we've already emailed about.

Stored as a JSON file (state.json) at the repo root and committed back by
the GitHub Action after each successful run. This is what makes the
toolkit only email when arXiv actually has new matching papers. (Committing
to the default branch also counts as repository activity, which keeps GitHub
from pausing the schedule after 60 quiet days.)

State layout:
  {
    "version": 2,
    "repository": "you/ArxivDaily",
    "last_run_utc": "2026-05-17T08:00:00+00:00",
    "last_sent_utc": "2026-05-17T08:00:00+00:00",
    "seen_ids": ["2405.01234", "2405.05678", ...]
  }

``repository`` records which GitHub repository the history belongs to. A
fresh fork inherits the original repository's state.json; when the names
differ, the history is ignored so the new owner's first digest is complete.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Iterable, List, Set

log = logging.getLogger(__name__)

_MAX_SEEN_IDS = 10000  # rolling cap so the file doesn't grow unboundedly


@dataclass
class State:
    version: int = 2
    repository: str = ""
    last_run_utc: str = ""
    last_sent_utc: str = ""
    seen_ids: List[str] = field(default_factory=list)

    @property
    def seen_set(self) -> Set[str]:
        return set(self.seen_ids)

    def mark_seen(self, ids: Iterable[str]) -> int:
        """Add ids (newest first, deduped, capped). Returns how many were new."""
        existing = self.seen_set
        new_unique = list(dict.fromkeys(i for i in ids if i not in existing))
        self.seen_ids = new_unique + self.seen_ids
        if len(self.seen_ids) > _MAX_SEEN_IDS:
            self.seen_ids = self.seen_ids[:_MAX_SEEN_IDS]
        return len(new_unique)

    def to_json(self) -> str:
        return json.dumps(
            {
                "version": self.version,
                "repository": self.repository,
                "last_run_utc": self.last_run_utc,
                "last_sent_utc": self.last_sent_utc,
                "seen_ids": self.seen_ids,
            },
            indent=2,
        )


def load(path: str, repository: str = "") -> State:
    if not os.path.exists(path):
        log.info("no existing state at %s — starting fresh", path)
        return State(repository=repository)
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception as e:  # noqa: BLE001
        log.warning("could not parse state file %s (%s) — starting fresh", path, e)
        return State(repository=repository)
    owner = str(data.get("repository", "") or "")
    if repository and owner and owner.lower() != repository.lower():
        log.info("state.json belongs to %s, not %s (fresh fork?) — starting with an empty history",
                 owner, repository)
        return State(repository=repository)
    return State(
        version=2,
        repository=repository or owner,
        last_run_utc=str(data.get("last_run_utc", "")),
        last_sent_utc=str(data.get("last_sent_utc", "")),
        seen_ids=[str(i) for i in data.get("seen_ids", [])],
    )


def save(path: str, state: State) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(state.to_json())
        f.write("\n")
    os.replace(tmp, path)
    log.info("wrote state to %s (%d ids)", path, len(state.seen_ids))


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
