"""Deterministic filtering before any LLM call: dedupe, location, freshness, keywords."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Iterable, List

from .common import Job, job_region


def dedupe(jobs: Iterable[Job]) -> List[Job]:
    best = {}
    for j in jobs:
        prev = best.get(j.key)
        # Prefer the copy with the longest description.
        if prev is None or len(j.description) > len(prev.description):
            best[j.key] = j
    return list(best.values())


def in_iraq(job: Job, cfg) -> bool:
    loc = (job.location or "").lower()
    return any(re.search(rf"\b{re.escape(t)}\b", loc) for t in cfg["search"]["iraq_locations"])


def is_excluded_location(job: Job, cfg) -> bool:
    if job_region() == "iraq_only":
        return not in_iraq(job, cfg)
    return in_iraq(job, cfg)


def is_excluded_title(job: Job, cfg) -> bool:
    title = (job.title or "").lower()
    return any(re.search(rf"\b{re.escape(t)}\b", title) for t in cfg["search"].get("exclude_title_terms", []))


def is_fresh(job: Job, cfg) -> bool:
    if job.posted_at is None:
        return True  # unknown date: let the seen-state stop repeats
    cutoff = datetime.now(timezone.utc) - timedelta(days=cfg["search"]["max_age_days"])
    return job.posted_at >= cutoff


def score_keywords(job: Job, cfg) -> None:
    p = cfg["prefilter"]
    title, desc = job.title.lower(), job.description.lower()
    score, hits, core = 0.0, [], False
    for s in p["skills"]:
        rx = re.compile(s["pattern"], re.I)
        in_title, in_desc = bool(rx.search(title)), bool(rx.search(desc))
        if in_title or in_desc:
            hits.append(s["name"])
            core = core or s.get("core", False)
            score += s["weight"] * (p["title_multiplier"] if in_title else 1)
    job.prefilter_score = score if core else 0.0
    job.prefilter_hits = hits


def prefilter(jobs: List[Job], cfg) -> List[Job]:
    for j in jobs:
        score_keywords(j, cfg)
    kept = [j for j in jobs if j.prefilter_score >= cfg["prefilter"]["min_score"]]
    kept.sort(key=lambda j: j.prefilter_score, reverse=True)
    return kept[: cfg["prefilter"]["max_candidates"]]
