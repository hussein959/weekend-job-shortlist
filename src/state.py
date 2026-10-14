"""Remember which jobs were already screened so they are not re-sent on every run."""
from __future__ import annotations

import json
from datetime import date, timedelta

from .common import ROOT

PATH = ROOT / "state" / "seen.json"
KEEP_DAYS = 60


class Seen:
    def __init__(self):
        self.data = json.loads(PATH.read_text()) if PATH.exists() else {}

    def __contains__(self, key: str) -> bool:
        return key in self.data

    def add(self, key: str) -> None:
        self.data[key] = date.today().isoformat()

    def save(self) -> None:
        cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
        self.data = {k: v for k, v in self.data.items() if v >= cutoff}
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(self.data, indent=0, sort_keys=True))
