"""Weekend job-application assistant.

    python -m src.main             full run: search, match, tailor, email
    python -m src.main --dry-run   search + keyword pre-filter only (no LLM, no email)
    python -m src.main --no-email  full run but only write files to output/
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date

from .common import ROOT, job_region, load_config, log, slugify
from .filters import dedupe, is_excluded_location, is_excluded_title, is_fresh, prefilter
from .sources import fetch_all
from .state import Seen


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="search and pre-filter only")
    ap.add_argument("--no-email", action="store_true", help="write files but do not send email")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # harmless font-map warnings

    try:
        from dotenv import load_dotenv  # local runs only
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    cfg = load_config()
    region = job_region()
    log.info("Job region: %s", region.replace("_", " "))
    if region == "iraq_only" and not os.environ.get("JSEARCH_API_KEY"):
        log.warning("JOB_REGION=iraq_only works best with JSEARCH_API_KEY: the free job boards list "
                    "almost no jobs located in Iraq.")
    today = date.today().isoformat()
    seen = Seen()

    raw = fetch_all(cfg)
    jobs = dedupe(raw)
    jobs = [j for j in jobs if not is_excluded_location(j, cfg) and not is_excluded_title(j, cfg)]
    jobs = [j for j in jobs if is_fresh(j, cfg) and j.key not in seen]
    candidates = prefilter(jobs, cfg)
    log.info("Fetched %d, %d new & eligible, %d pass keyword pre-filter", len(raw), len(jobs), len(candidates))

    if args.dry_run:
        for j in candidates:
            print(f"{j.prefilter_score:5.1f}  {j.title[:55]:55}  {j.company[:25]:25}  {j.location[:30]:30}  {','.join(j.prefilter_hits)}")
        return

    from .cv_loader import load_cv
    from .llm import LLM
    from .mailer import build_email, send_email
    from .matcher import screen_all
    from .render import render_docx
    from .tailor import tailor_cv

    cv_text = load_cv()
    llm = LLM()
    all_matches = screen_all(llm, candidates, cv_text, cfg)
    if candidates and not any(j.match for j in candidates):
        # Fail the run (GitHub then emails a failure notice) instead of sending a
        # misleading "no matches" shortlist. Nothing is marked as seen.
        raise SystemExit("Every screening call failed; check the LLM secrets and the log above.")
    matches = all_matches[: cfg["matching"]["max_applications"]]
    tailor_model = llm.model_for(cfg["models"]["tailoring"])
    log.info("%d strong matches; tailoring %d with %s model (%s)",
             len(all_matches), len(matches), cfg["models"]["tailoring"], tailor_model)

    out_dir = ROOT / "output" / today
    packages = []
    for i, job in enumerate(matches, 1):
        try:
            cv, warnings = tailor_cv(llm, job, cv_text, tailor_model)
        except Exception as e:
            log.warning("Tailoring failed for %s @ %s: %s", job.title, job.company, e)
            continue
        name = slugify(cv.get("name") or "CV", 20)
        path = render_docx(cv, out_dir / f"{i:02d}_{name}_{slugify(job.company, 25)}_{slugify(job.title, 30)}.docx")
        (path.with_suffix(".json")).write_text(json.dumps(
            {"job": {"title": job.title, "company": job.company, "location": job.location, "url": job.url},
             "match": job.match, "warnings": warnings, "cv": cv}, indent=2, ensure_ascii=False))
        packages.append((job, path, warnings, cv.get("tailoring_notes", "")))

    stats = {"fetched": len(raw), "candidates": len(candidates), "matches": len(all_matches),
             "region": "Jobs in Iraq only" if region == "iraq_only" else "Jobs outside Iraq"}
    html_body, text_body = build_email(today, packages, stats)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "shortlist.html").write_text(html_body, encoding="utf-8")

    if not args.no_email and (packages or cfg["email"]["send_when_empty"]):
        subject = f"{cfg['email']['subject_prefix']} · {today} · {len(packages)} match{'es' if len(packages) != 1 else ''}"
        send_email(subject, html_body, text_body, [p for _, p, _, _ in packages])
        log.info("Email sent")

    # Only remember jobs once the email went out, so a failed run retries them next time.
    # Matches beyond today's tailoring cap are not remembered, so they carry over.
    sent = {j.key for j, _, _, _ in packages}
    overflow = {j.key for j in all_matches} - sent
    for j in candidates:
        if j.match and j.key not in overflow:
            seen.add(j.key)
    seen.save()


if __name__ == "__main__":
    main()
