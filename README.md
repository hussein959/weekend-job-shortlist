# Weekend Job Shortlist

Every Saturday and Sunday at 07:00 Baghdad time (04:00 UTC), a GitHub Actions run does the following:

1. **Searches** job APIs for software developer roles worldwide: Remotive, Arbeitnow, RemoteOK, Jobicy and Himalayas. If you add keys, it also searches Adzuna (8 countries) and JSearch (Google for Jobs, which covers LinkedIn, Indeed, Glassdoor and company sites).
2. **Filters** the results. It removes duplicates, roles located in Iraq, postings older than 7 days (the full week between runs) and jobs it already showed you. A keyword pre-filter then keeps the best 20 for your stack (.NET/C#, Flutter/Dart, PostgreSQL/PostGIS, MongoDB).
3. **Matches** each candidate job against your master CV using the cheap screening model (`LLM_SCREEN_MODEL`). It lists the job's requirements and marks each one met, partial or missing, using evidence from your CV. It also checks seniority and whether someone based in Iraq can apply. A role is kept only if it scores at least 65/100 and you meet at least 50% of its requirements.
4. **Tailors** your master CV for the best 2 matches per run, then **fact-checks** each one twice. Further matches carry over to the next run. Tailoring and the LLM fact-check use the model chosen in `config.yaml` (`models.tailoring: cheap` or `strong`). The two checks are:
   - an LLM audit against the master CV
   - a deterministic check that removes any skill or employer that is not in your CV
5. **Emails** you a shortlist. Each job has its link, company, score, why you match, gaps, a location note and the tailored `.docx` CV attached.

Nothing is ever submitted for you.

## Setup (about 15 minutes)

This repository is **public**, so GitHub Actions minutes are free. Your CV, keys and email password are never stored in it (see [Privacy](#privacy)).

1. Fork or push this code to a public GitHub repository. **Never commit your CV.**
2. Share your CV privately:
   - Upload your CV to Google Drive (PDF or `.docx`) or write it as a Google Doc.
   - Click **Share → General access → Anyone with the link → Viewer** and copy the link.
   - Save the link as the repository secret `CV_URL`. Do not paste it anywhere public.
3. Add repository secrets under **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Required | Value |
|---|---|---|
| `LLM_API_KEY` | yes | API key of your LLM provider |
| `LLM_BASE_URL` | yes* | Provider's OpenAI-compatible endpoint (*leave unset for OpenAI itself) |
| `LLM_SCREEN_MODEL` | yes | Cheap model ID: always used for screening, and for tailoring when `models.tailoring: cheap` |
| `LLM_MODEL` | yes* | Stronger model ID, used for tailoring when `models.tailoring: strong` (*defaults to `LLM_SCREEN_MODEL`) |
| `SMTP_USER` | yes | Your Gmail address |
| `SMTP_PASSWORD` | yes | Gmail **App Password**, not your normal password ([create one](https://myaccount.google.com/apppasswords); requires 2-Step Verification) |
| `EMAIL_TO` | no | Where to send the shortlist (defaults to `SMTP_USER`) |
| `SMTP_HOST` / `SMTP_PORT` | no | Defaults `smtp.gmail.com` / `465` |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | no | Free at https://developer.adzuna.com |
| `JSEARCH_API_KEY` | no | Free tier at https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch |
| `CV_URL` | yes | Google Drive / Google Docs share link to your CV (see step 2) |

4. Go to **Actions → Weekend job shortlist → Run workflow** to test it once (manual runs work on any day). After that it runs every Saturday and Sunday on its own.

## Choosing the region

The `JOB_REGION` setting chooses where to look:

| Value | Jobs kept |
|---|---|
| `outside_iraq` (default) | Every country except Iraq, including remote roles |
| `iraq_only` | Only jobs located in Iraq (Baghdad, Erbil, Basra, ...) |

- **Local runs:** set `JOB_REGION=...` in your `.env`.
- **GitHub runs:** go to Settings → Secrets and variables → Actions → **Variables** tab and add a repository variable named `JOB_REGION`. It is not a secret.

The free job boards list almost no jobs located in Iraq. For `iraq_only`, add a `JSEARCH_API_KEY`: JSearch then searches Google Jobs (LinkedIn, Bayt, company sites) in Iraq. The cities counted as Iraq are the `iraq_locations` list in `config.yaml`.

## Tuning

Everything is in [`config.yaml`](config.yaml). The main cost settings:

| Setting | Default | Effect |
|---|---|---|
| `prefilter.max_candidates` | 20 | Jobs screened by the cheap model per run |
| `matching.max_applications` | 2 | Tailored CVs per run |
| `models.tailoring` | `strong` | `cheap` = lower cost, `strong` = better CV writing |

To change the schedule, edit the `cron` line in `.github/workflows/daily-shortlist.yml` (`6,0` = Saturday and Sunday).

Search queries, excluded locations, keyword weights, score thresholds and your relocation and remote preferences are in the same file.

## Privacy

What is public in this repo:
- the code and `config.yaml`
- the Actions run logs, which show job titles, companies and match scores (never CV text, keys or the CV link)

What is never in the repo:
- **Your CV.** It is downloaded from the `CV_URL` secret at run time. `.gitignore` blocks `cv/`, `*.pdf` and `*.docx`.
- **Keys, passwords, your email address and the CV link.** They are encrypted repository secrets, and GitHub masks their values in logs. If downloading the CV fails, the error message leaves out the link.
- **Tailored CVs.** They are only emailed to you. No run artifacts are uploaded, because anyone could download them from a public repo.

Who can use the secrets: only runs started by the schedule or by someone with write access. Pull requests from forks never receive them.

## Local run

```bash
git clone https://github.com/hussein959/weekend-job-shortlist.git
cd weekend-job-shortlist
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill it in (CV_URL, or CV_PATH to a file outside this folder)
python -m src.main --dry-run    # search + pre-filter only, no keys needed
python -m src.main --no-email   # full run, files written to output/<date>/ (not emailed)
python -m src.main              # full run and email
```

`.env` is ignored by git, so local keys and settings never reach the repository.

### Using a local AI agent instead of an API key

If a command-line AI agent is installed and signed in on your machine, local runs can use it instead of an API key:

```ini
LLM_BACKEND=cli
LLM_CLI_COMMAND=<agent command in non-interactive mode, with tools disabled> --model {model}
LLM_SCREEN_MODEL=<cheap model name>
LLM_MODEL=<strong model name>
```

Each prompt is sent to the command on stdin, and the command runs in an empty temporary folder. This works only on your machine. The scheduled GitHub run still uses `LLM_BACKEND=api` and the repository secrets.

## Notes

- GitHub pauses scheduled workflows in public repos after 60 days without any commits. If that happens, re-enable it from the Actions tab.
- The list of jobs already seen is stored in the GitHub Actions cache, so the same job is not sent twice. GitHub deletes cache entries that are not used for 7 days. If you disable the workflow for more than a week, old jobs may be screened again once.
- Each run also uploads its CVs as a downloadable artifact on the run page, kept for 14 days.
- The tailored CVs are fact-checked, but read each one before you send it. The email lists any corrections the checker made.
- Adzuna returns only description snippets, so its matches are judged more cautiously.
