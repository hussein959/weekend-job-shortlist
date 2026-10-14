"""Tailor the master CV to one job, then verify nothing was invented.

Three layers of protection against fabrication:
1. The tailoring prompt only allows selecting, reordering and rephrasing CV facts.
2. A second LLM pass audits the tailored CV against the master CV and removes
   anything unsupported.
3. A deterministic check drops listed skills / employers that do not appear in the
   master CV text at all.
"""
from __future__ import annotations

import re
from typing import List, Tuple

from .common import Job, log
from .llm import LLM
from .matcher import match_summary

SCHEMA = """{
  "name": "...",
  "headline": "one line, e.g. 'Backend & Mobile Developer | .NET, C#, Flutter'",
  "contact": {"email": "...", "phone": "...", "location": "...", "linkedin": "...", "github": "...", "website": "..."},
  "summary": "3-4 sentences",
  "skills": [{"category": "...", "items": ["..."]}],
  "experience": [{"title": "...", "company": "...", "location": "...", "dates": "...", "bullets": ["..."]}],
  "projects": [{"name": "...", "link": "...", "tech": ["..."], "bullets": ["..."]}],
  "education": [{"degree": "...", "institution": "...", "dates": "...", "details": "..."}],
  "certifications": ["..."],
  "languages": ["..."],
  "extra_sections": [{"title": "...", "items": ["..."]}],
  "tailoring_notes": "1-2 sentences for the candidate: what you emphasised and why"
}"""

TAILOR_SYSTEM = """You are an expert CV writer. You tailor a candidate's master CV to a
specific job WITHOUT inventing anything. Respond with a single JSON object only."""

TAILOR_PROMPT = """MASTER CV (the only source of truth)
<<<
{cv}
>>>

TARGET JOB
Title: {title}
Company: {company}
Location: {location}
Description:
<<<
{description}
>>>

SCREENING NOTES (what matched, what to emphasise, gaps)
{notes}

Tailor the CV for this job. Hard rules:
- Use ONLY facts present in the master CV. Never add employers, job titles, dates,
  degrees, certifications, technologies, metrics, numbers, team sizes or achievements
  that are not stated there. Do not upgrade skill levels or years of experience.
- You MAY: reorder sections and bullets, choose which projects/bullets to include,
  rephrase bullets to foreground relevant work, mirror the job's terminology ONLY
  where the CV genuinely shows that skill, and shorten or drop irrelevant details.
- Keep every employment entry (to avoid unexplained gaps) with titles, companies and
  dates copied exactly; irrelevant roles may be shortened to 1-2 bullets.
- Copy contact details exactly; omit any contact field that is not in the CV.
- Put the most relevant skills category first. Do not mention gaps in the CV.
- Omit sections/fields that would be empty.

Return JSON in exactly this shape:
{schema}"""

VERIFY_SYSTEM = """You are a meticulous fact-checker. You compare a tailored CV with
the master CV it was derived from. Respond with a single JSON object only."""

VERIFY_PROMPT = """MASTER CV (source of truth)
<<<
{cv}
>>>

TAILORED CV (JSON)
<<<
{tailored}
>>>

Find every claim in the tailored CV that is NOT supported by the master CV: invented
skills, technologies, employers, titles, dates, degrees, certifications, numbers or
metrics, achievements, or exaggerated seniority. Rephrasing of genuine facts is fine.

Return JSON:
{{
  "issues": [{{"claim": "...", "reason": "..."}}],
  "corrected_cv": <the tailored CV JSON with every unsupported claim removed or
                   rewritten to match the master CV; identical if there are no issues>
}}"""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9#+]+", " ", (s or "").lower()).strip()


def deterministic_check(cv: dict, master_text: str) -> Tuple[dict, List[str]]:
    master = _norm(master_text)
    warnings = []
    for group in cv.get("skills") or []:
        kept = []
        for item in group.get("items") or []:
            # Accept if the skill, or each of its main words, appears in the master CV.
            words = [w for w in _norm(item).split() if len(w) > 1]
            if _norm(item) in master or (words and all(w in master for w in words)):
                kept.append(item)
            else:
                warnings.append(f"Removed skill not found in master CV: {item}")
        group["items"] = kept
    cv["skills"] = [g for g in cv.get("skills") or [] if g.get("items")]
    for exp in cv.get("experience") or []:
        company = _norm(exp.get("company", ""))
        if company and company not in master:
            warnings.append(f"Employer not found verbatim in master CV, please check: {exp.get('company')}")
    return cv, warnings


def tailor_cv(llm: LLM, job: Job, master_text: str, model: str) -> Tuple[dict, List[str]]:
    import json

    draft = llm.json(
        TAILOR_SYSTEM,
        TAILOR_PROMPT.format(cv=master_text, title=job.title, company=job.company, location=job.location,
                             description=job.description[:12000], notes=match_summary(job), schema=SCHEMA),
        model=model, max_tokens=8000,
    )
    notes = draft.get("tailoring_notes", "")
    audit = llm.json(
        VERIFY_SYSTEM,
        VERIFY_PROMPT.format(cv=master_text, tailored=json.dumps(draft, ensure_ascii=False, indent=1)),
        model=model, max_tokens=10000,
    )
    issues = audit.get("issues") or []
    cv = audit.get("corrected_cv") if issues and isinstance(audit.get("corrected_cv"), dict) else draft
    cv.setdefault("tailoring_notes", notes)
    warnings = [f"Fact-check removed/corrected: {i.get('claim')} ({i.get('reason')})" for i in issues]
    cv, more = deterministic_check(cv, master_text)
    warnings += more
    if warnings:
        log.info("  %d fact-check adjustments for %s @ %s", len(warnings), job.title, job.company)
    return cv, warnings
