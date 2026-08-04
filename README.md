# Flock Safety Misuse Tracker

An automatically-updating dataset tracking U.S. law enforcement officers and
personnel who have been **fired, forced to resign, arrested, charged, or
convicted** for misusing Flock Safety ALPR (automated license plate reader)
technology.

- `data/cases.json` — the structured, running dataset. Seeded from a research
  pass current to **2026-07-30**.
- `data/weekly-log/` — one dated markdown report per weekly run, summarizing
  what changed.
- `scripts/update_tracker.py` — calls the Claude API (with the web search
  tool) to look for new developments and merges them into `cases.json`.
- `.github/workflows/weekly-update.yml` — runs the script every Monday and
  commits any changes automatically.

## Setup (one-time)

1. **Create the repo.** Push this folder to a new GitHub repository (public
   or private — a public repo gets free Actions minutes; a private repo gets
   2,000 free minutes/month, which is far more than this needs).

   ```bash
   cd flock-misuse-tracker
   git init
   git add .
   git commit -m "Initial commit: seed dataset + weekly tracker"
   git branch -M main
   git remote add origin https://github.com/<your-username>/<your-repo>.git
   git push -u origin main
   ```

2. **Add your Anthropic API key as a secret.**
   In the GitHub repo: **Settings → Secrets and variables → Actions → New
   repository secret**
   - Name: `ANTHROPIC_API_KEY`
   - Value: your key from [console.anthropic.com](https://console.anthropic.com)

   Usage is billed to your own Anthropic API account. Each weekly run does a
   handful of web searches and one model call — typically well under $0.10/run.

3. **(Optional) Test it immediately** instead of waiting for Monday: go to the
   **Actions** tab → "Weekly Flock Misuse Tracker Update" → **Run workflow**.

That's it — from here it runs unattended every Monday at 13:00 UTC, appends
any new cases or status changes to `data/cases.json`, and writes a dated
report to `data/weekly-log/`.

## Adjusting the schedule

Edit the `cron` line in `.github/workflows/weekly-update.yml`. Cron syntax is
`minute hour day month weekday`, all in UTC — e.g. `0 13 * * 1` = every Monday
at 13:00 UTC.

## Adjusting the model

Set the `ANTHROPIC_MODEL` env var in the workflow file if you want to pin a
specific model string (defaults to `claude-sonnet-5`).

## Data schema

`data/cases.json` uses a two-layer schema: `incidents[]` (reported enforcement
events, which may involve multiple officers and may be reported before every
name is public) and `cases[]` (individual named people, each linked to an
incident via `parent_incident_id`). This exists specifically to handle sweeps
like Georgia's 2026 audit-driven arrests, where "18 officers arrested" is
reported well before all 18 are named. See [`SCHEMA.md`](SCHEMA.md) for the
full field reference and the reasoning behind the split.

`data/cases.json` also has an `aggregate_trackers` array for external running
counts (Institute for Justice's stalking tally, Georgia's arrest count, etc.)
that should be checked against, not summed with, the individual case list —
they overlap only partially.

## Data quality / review model

Everything the weekly script writes is `verified: false` by default,
including auto-linked cases (e.g. a newly-named officer matched to an
existing unnamed sweep). The script auto-links its best guess rather than
skipping ambiguous matches, and flags anything where an incident's
`identified_count` exceeds its `reported_count` — that combination means
either a bad link or a `reported_count` that needs correcting. Check
`data/weekly-log/` after each run and periodically review `verified: false`
entries in `data/cases.json`.

## Known limitations

- This is a **best-effort, LLM-assisted tracker**, not an official or legal
  record. Always check the cited sources before relying on any entry.
- Coverage depends entirely on what's been publicly reported; most misuse is
  believed to go undetected, so this dataset is a documented floor, not a
  true total.
- The weekly search window is narrow (~7-10 days) by design, to keep runs
  cheap and reports incremental — it isn't meant to re-verify the entire
  dataset each time.
