"""Job sources. Each fetcher returns a list of Job; failures are logged and skipped.

Free, keyless sources: Remotive, Arbeitnow, RemoteOK, Jobicy, Himalayas.
Optional (need free API keys): Adzuna (many countries), JSearch (Google for Jobs:
LinkedIn / Indeed / Glassdoor / company sites).
"""
from __future__ import annotations

from typing import Callable, List

import requests

from .common import Job, env, html_to_text, job_region, log, parse_dt

UA = {"User-Agent": "Mozilla/5.0 (compatible; personal-job-shortlist/1.0)"}
TIMEOUT = 30


def _get(url: str, **kw):
    headers = {**UA, **kw.pop("headers", {})}
    r = requests.get(url, headers=headers, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r.json()


def fetch_remotive(cfg) -> List[Job]:
    data = _get("https://remotive.com/api/remote-jobs", params={"category": "software-dev"})
    return [
        Job(
            source="Remotive",
            title=j.get("title", ""),
            company=j.get("company_name", ""),
            location=j.get("candidate_required_location") or "Remote",
            url=j.get("url", ""),
            description=html_to_text(j.get("description")),
            posted_at=parse_dt(j.get("publication_date")),
            salary=j.get("salary") or "",
        )
        for j in data.get("jobs", [])
    ]


def fetch_arbeitnow(cfg) -> List[Job]:
    jobs = []
    for page in (1, 2, 3):
        data = _get("https://www.arbeitnow.com/api/job-board-api", params={"page": page})
        for j in data.get("data", []):
            loc = j.get("location") or ""
            if j.get("remote"):
                loc = f"{loc} (Remote)".strip()
            jobs.append(Job(
                source="Arbeitnow",
                title=j.get("title", ""),
                company=j.get("company_name", ""),
                location=loc,
                url=j.get("url", ""),
                description=html_to_text(j.get("description")),
                posted_at=parse_dt(j.get("created_at")),
            ))
    return jobs


def fetch_remoteok(cfg) -> List[Job]:
    data = _get("https://remoteok.com/api")
    jobs = []
    for j in data:
        if not isinstance(j, dict) or not j.get("position"):
            continue  # first element is a legal notice
        salary = ""
        if j.get("salary_min") and j.get("salary_max"):
            salary = f"${j['salary_min']:,}-${j['salary_max']:,}"
        jobs.append(Job(
            source="RemoteOK",
            title=j.get("position", ""),
            company=j.get("company", ""),
            location=j.get("location") or "Remote",
            url=j.get("url") or f"https://remoteok.com/remote-jobs/{j.get('id')}",
            description=html_to_text(j.get("description")),
            posted_at=parse_dt(j.get("epoch") or j.get("date")),
            salary=salary,
        ))
    return jobs


def fetch_jobicy(cfg) -> List[Job]:
    jobs = []
    for tag in cfg["search"].get("jobicy_tags", []):
        try:
            data = _get("https://jobicy.com/api/v2/remote-jobs", params={"count": 50, "tag": tag})
        except Exception as e:  # unknown tags return errors; keep going
            log.debug("Jobicy tag %s failed: %s", tag, e)
            continue
        for j in data.get("jobs", []):
            jobs.append(Job(
                source="Jobicy",
                title=html_to_text(j.get("jobTitle")),
                company=j.get("companyName", ""),
                location=j.get("jobGeo") or "Remote",
                url=j.get("url", ""),
                description=html_to_text(j.get("jobDescription") or j.get("jobExcerpt")),
                posted_at=parse_dt(j.get("pubDate")),
            ))
    return jobs


def fetch_himalayas(cfg) -> List[Job]:
    jobs = []
    for q in cfg["search"]["queries"]:
        data = _get("https://himalayas.app/jobs/api/search", params={"q": q})
        for j in data.get("jobs", []):
            restr = j.get("locationRestrictions") or []
            names = [r.get("name", "") if isinstance(r, dict) else str(r) for r in restr]
            jobs.append(Job(
                source="Himalayas",
                title=j.get("title", ""),
                company=j.get("companyName", ""),
                location=", ".join(n for n in names if n) or "Remote (worldwide)",
                url=j.get("applicationLink") or j.get("guid") or "",
                description=html_to_text(j.get("description") or j.get("excerpt")),
                posted_at=parse_dt(j.get("pubDate")),
            ))
    return jobs


def fetch_adzuna(cfg) -> List[Job]:
    app_id, app_key = env("ADZUNA_APP_ID"), env("ADZUNA_APP_KEY")
    if not (app_id and app_key) or job_region() == "iraq_only":
        return []  # Adzuna does not cover Iraq
    a = cfg["search"]["adzuna"]
    jobs = []
    for country in a["countries"]:
        try:
            data = _get(
                f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
                params={
                    "app_id": app_id, "app_key": app_key, "results_per_page": 50,
                    "what_or": a["what_or"], "max_days_old": cfg["search"]["max_age_days"],
                    "content-type": "application/json",
                },
            )
        except Exception as e:
            log.warning("Adzuna %s failed: %s", country, e)
            continue
        for j in data.get("results", []):
            jobs.append(Job(
                source=f"Adzuna-{country.upper()}",
                title=html_to_text(j.get("title")),
                company=(j.get("company") or {}).get("display_name", ""),
                location=(j.get("location") or {}).get("display_name", country.upper()),
                url=j.get("redirect_url", ""),
                # Adzuna only returns a snippet; the matcher is told when text is short.
                description=html_to_text(j.get("description")),
                posted_at=parse_dt(j.get("created")),
            ))
    return jobs


def fetch_jsearch(cfg) -> List[Job]:
    key = env("JSEARCH_API_KEY")
    if not key:
        return []
    js = cfg["search"]["jsearch"]
    headers = {"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}
    jobs = []
    iraq = job_region() == "iraq_only"
    for q in js["queries"]:
        params = {"query": f"{q} in Iraq" if iraq else q, "page": 1, "num_pages": 1,
                  "date_posted": js.get("date_posted", "week")}
        if iraq:
            params["country"] = "iq"
        try:
            data = _get(
                "https://jsearch.p.rapidapi.com/search", headers=headers,
                params=params,
            )
        except Exception as e:
            log.warning("JSearch '%s' failed: %s", q, e)
            continue
        for j in data.get("data", []):
            loc = ", ".join(x for x in (j.get("job_city"), j.get("job_state"), j.get("job_country")) if x)
            if j.get("job_is_remote"):
                loc = f"{loc} (Remote)".strip()
            jobs.append(Job(
                source=f"JSearch/{j.get('job_publisher') or 'web'}",
                title=j.get("job_title", ""),
                company=j.get("employer_name", ""),
                location=loc or "Unspecified",
                url=j.get("job_apply_link") or j.get("job_google_link") or "",
                description=j.get("job_description") or "",
                posted_at=parse_dt(j.get("job_posted_at_datetime_utc")),
            ))
    return jobs


FETCHERS: List[Callable] = [
    fetch_remotive, fetch_arbeitnow, fetch_remoteok, fetch_jobicy,
    fetch_himalayas, fetch_adzuna, fetch_jsearch,
]


def fetch_all(cfg) -> List[Job]:
    all_jobs: List[Job] = []
    for fetch in FETCHERS:
        name = fetch.__name__.replace("fetch_", "")
        try:
            jobs = fetch(cfg)
            log.info("%-10s %4d jobs", name, len(jobs))
            all_jobs.extend(j for j in jobs if j.title and j.url)
        except Exception as e:
            log.warning("%-10s failed: %s", name, e)
    return all_jobs
