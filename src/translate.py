"""Optional faithful translation of the master CV (config: cv_language).

When a profile sets cv_language: english and the master CV is not in English, the
master CV is translated once and that translation becomes the source of truth for
screening, tailoring and every fact-check. The translation is cached in state/, so it
is only redone when the master CV changes.
"""
from __future__ import annotations

import hashlib
import json
import re

from .common import ROOT, log
from .llm import LLM

SYSTEM = """You are a professional translator of CVs. You translate faithfully and
never add, remove, embellish or reinterpret anything. Respond with a single JSON object only."""

PROMPT = """Translate this CV into clear, professional English.

Rules:
- Translate every statement faithfully, with the same meaning and level of detail.
  Do not add skills, duties, achievements, numbers, dates or job titles, and do not
  strengthen or soften any claim. Keep vague statements vague.
- Keep names, phone numbers, email addresses, links and numbers exactly as written.
  Transliterate Arabic personal names, company names and place names into Latin letters
  (e.g. "Al-Noor Company", "Baghdad - Al-Mansour").
- If the original contains something unclear or contradictory, translate it as is.
- Keep the original structure (headings, lists) as plain text lines.

CV:
<<<
{cv}
>>>

Return JSON: {{"translation": "<the full English CV as plain text>"}}"""


def _is_english(text: str) -> bool:
    letters = re.findall(r"[^\W\d_]", text)
    latin = sum(1 for c in letters if c.isascii())
    return bool(letters) and latin / len(letters) > 0.8


def prepare_master_cv(llm: LLM, cfg: dict, cv_text: str, model: str) -> str:
    """Return the master CV text in the profile's CV language."""
    if cfg.get("cv_language", "same") != "english" or _is_english(cv_text):
        return cv_text
    digest = hashlib.sha256(cv_text.encode()).hexdigest()[:16]
    cache = ROOT / "state" / f"cv-translation-{digest}.json"
    if cache.exists():
        log.info("Using cached English translation of the master CV")
        return json.loads(cache.read_text())["translation"]
    log.info("Translating the master CV to English (once; cached afterwards)")
    result = llm.json(SYSTEM, PROMPT.format(cv=cv_text), model=model, max_tokens=6000)
    translation = (result.get("translation") or "").strip()
    if len(translation) < 300:
        raise SystemExit("CV translation came back empty or too short.")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"translation": translation}, ensure_ascii=False, indent=1))
    return translation
