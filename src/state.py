"""Remember which jobs were already screened so they are not re-sent on every run."""
from __future__ import annotations

import json
from datetime import date, timedelta

from .common import ROOT, config_path

KEEP_DAYS = 60


def _path():
    """One seen-list per search profile, so profiles never hide each other's jobs."""
    stem = config_path().stem
    return ROOT / "state" / ("seen.json" if stem == "config" else f"seen-{stem}.json")


class Seen:
    def __init__(self):
        self.path = _path()
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {}

    def __contains__(self, key: str) -> bool:
        return key in self.data

    def add(self, key: str) -> None:
        self.data[key] = date.today().isoformat()

    def save(self) -> None:
        cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
        self.data = {k: v for k, v in self.data.items() if v >= cutoff}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=0, sort_keys=True))
