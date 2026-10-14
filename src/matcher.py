"""LLM screening: compare each job's requirements against the master CV."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import List

from .common import Job, log
from .llm import LLM

SYSTEM = """You are a strict, honest technical recruiter. You compare a job posting's
requirements against a candidate's CV and judge the fit. You never assume skills that
are not evidenced in the CV. Respond with a single JSON object and nothing else."""

PROMPT = """CANDIDATE CONTEXT
- Based in: {based_in}
- Open to relocation: {relocation}
- Open to remote work: {remote}
- Target roles: {titles}

CANDIDATE CV
<<<
{cv}
>>>

JOB POSTING
Title: {title}
Company: {company}
Location: {location}
{short_note}Description:
<<<
{description}
>>>

Task:
1. Extract the job's concrete requirements (skills, technologies, years of experience,
   domain knowledge, degree, languages). Ignore generic soft-skill filler.
2. For each requirement decide met = "yes", "partial" or "no", based ONLY on evidence
   in the CV, and quote or paraphrase that evidence (empty string if none).
3. Judge seniority fit and whether a candidate based in {based_in} can realistically
   apply (e.g. "US citizens only", "must already live in the EU", security clearance).
4. Give an overall score 0-100 for how well the candidate genuinely matches.
   70+ means a strong, credible application; below 50 means not worth applying.

Return JSON exactly in this shape:
{{
  "requirements": [{{"requirement": "...", "met": "yes|partial|no", "evidence": "..."}}],
  "score": 0,
  "seniority_fit": "good|stretch|mismatch",
  "location_eligible": "yes|unclear|no",
  "location_note": "one short sentence",
  "why_match": "2-3 sentences, specific, written to the candidate (use 'you')",
  "gaps": ["short phrases for the main missing requirements"],
  "emphasise": ["CV skills/projects/experience most worth highlighting for this role"]
}}"""


def requirement_ratio(match: dict) -> float:
    reqs = match.get("requirements") or []
    if not reqs:
        return 0.0
    pts = {"yes": 1.0, "partial": 0.5}
    return sum(pts.get(str(r.get("met", "")).lower(), 0.0) for r in reqs) / len(reqs)


def screen_job(llm: LLM, job: Job, cv: str, cfg) -> Job:
    c = cfg["candidate"]
    short = "NOTE: only a snippet of the description is available; judge cautiously.\n" if len(job.description) < 800 else ""
    prompt = PROMPT.format(
        based_in=c["based_in"], relocation=c["open_to_relocation"], remote=c["open_to_remote"],
        titles=", ".join(c["target_titles"]), cv=cv, title=job.title, company=job.company,
        location=job.location, short_note=short, description=job.description[:12000],
    )
    try:
        job.match = llm.json(SYSTEM, prompt, model=llm.screen_model, max_tokens=3000)
        job.match["requirement_ratio"] = round(requirement_ratio(job.match), 2)
    except Exception as e:
        log.warning("Screening failed for %s @ %s: %s", job.title, job.company, e)
        job.match = {}
    return job


def is_match(job: Job, cfg) -> bool:
    m, mc = job.match, cfg["matching"]
    if not m:
        return False
    return (
        int(m.get("score", 0)) >= mc["min_score"]
        and m.get("requirement_ratio", 0) >= mc["min_requirement_ratio"]
        and m.get("seniority_fit") != "mismatch"
        and m.get("location_eligible") != "no"
    )


def screen_all(llm: LLM, jobs: List[Job], cv: str, cfg) -> List[Job]:
    with ThreadPoolExecutor(max_workers=cfg["matching"]["workers"]) as pool:
        screened = list(pool.map(lambda j: screen_job(llm, j, cv, cfg), jobs))
    for j in screened:
        if j.match:
            log.info("  %3s%% req=%.2f  %s @ %s", j.match.get("score"), j.match.get("requirement_ratio", 0),
                     j.title[:60], j.company[:30])
    matches = [j for j in screened if is_match(j, cfg)]
    matches.sort(key=lambda j: (int(j.match.get("score", 0)), j.match.get("requirement_ratio", 0)), reverse=True)
    return matches


def match_summary(job: Job) -> str:
    return json.dumps({k: job.match.get(k) for k in ("emphasise", "gaps", "requirements")}, ensure_ascii=False)
