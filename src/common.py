"""Shared types and helpers."""
from __future__ import annotations

import html
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("jobs")


def config_path() -> Path:
    """The search profile: CONFIG_FILE (relative to the project folder) or config.yaml."""
    path = Path(os.environ.get("CONFIG_FILE", "").strip() or "config.yaml")
    return path if path.is_absolute() else ROOT / path


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        raise SystemExit(f"CONFIG_FILE not found: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


REGIONS = ("outside_iraq", "iraq_only")


def job_region() -> str:
    """Which jobs to look for: JOB_REGION=outside_iraq (default) or iraq_only."""
    region = (os.environ.get("JOB_REGION", "").strip().lower() or "outside_iraq").replace("-", "_")
    if region not in REGIONS:
        raise SystemExit(f"JOB_REGION must be one of {', '.join(REGIONS)}; got {region!r}")
    return region


def env(name: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    value = os.environ.get(name, "").strip() or default
    if required and not value:
        raise SystemExit(f"Missing required environment variable / secret: {name}")
    return value


@dataclass
class Job:
    source: str
    title: str
    company: str
    location: str
    url: str
    description: str
    posted_at: Optional[datetime] = None
    salary: str = ""
    prefilter_score: float = 0.0
    prefilter_hits: list = field(default_factory=list)
    match: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Stable identity used for de-duplication across sources and days."""
        norm = lambda s: re.sub(r"[^a-z0-9]+", "", (s or "").lower())
        return f"{norm(self.company)}|{norm(self.title)}"


def html_to_text(s: Any) -> str:
    if not s:
        return ""
    s = str(s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\r\f\v\xa0]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s)
    return s.strip()


def parse_dt(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
            ts = float(value)
            if ts > 1e12:  # milliseconds
                ts /= 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        s = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s.replace(" ", "T", 1) if "T" not in s else s)
        except ValueError:
            dt = parsedate_to_datetime(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def slugify(s: str, max_len: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s or "").strip("-")
    return s[:max_len].strip("-") or "job"
