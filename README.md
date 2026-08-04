# Flock Safety Misuse Tracker

An automatically-updating dataset tracking U.S. law enforcement officers and
personnel who have been **fired, forced to resign, arrested, charged, or
convicted** for misusing Flock Safety ALPR (automated license plate reader)
technology.

- `data/cases.json` — the structured, running dataset. Seeded from a research
  pass current to **2026-07-30**, and kept current automatically every other
  day (see below).
- `data/weekly-log/` — one dated markdown report per automated run,
  summarizing what changed.
- `scripts/update_tracker.py` — calls the Claude API (with the web search
  tool) to look for new developments and merges them into `cases.json`.

## How it stays current

A scheduled job re-checks the Flock misuse story every other day, searching
for developments in roughly the last 7-10 days, and appends or updates
entries in `data/cases.json`. Everything it writes lands as `verified: false`
— see **Data quality / review model** below — and a summary of each run is
saved to `data/weekly-log/`.

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

Everything the automated script writes is `verified: false` by default,
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
- The search window per run is narrow (~7-10 days) by design, to keep runs
  cheap and reports incremental — it isn't meant to re-verify the entire
  dataset each time.
