# Flock Safety Misuse Tracker

An automatically-updating dataset tracking ALPR (automated license plate
reader) misuse and abuse by law enforcement - stalking, unauthorized access,
wrongful stops, and other misconduct - sourced daily from the
[Institute for Justice's ALPR abuse database](https://ij.org/the-ij-database-of-alpr-abuse/).

IJ's database covers every ALPR vendor it has documented (Flock, Rekor,
Vigilant, Guardian, NDI, and some unspecified-vendor entries), and this
tracker keeps all of them rather than filtering to Flock only - each entry
carries `manufacturer` and a boolean `is_flock` so consumers can filter down
if they only want the Flock subset. Started as Flock-specific (hence the
repo name); broadened once it became clear the underlying misuse and
outcome patterns aren't vendor-specific and the other vendors' data was
worth keeping.

- `data/cases.json` - the structured, running dataset.
- `data/run-log/` - one dated markdown report per scrape, summarizing what
  changed.
- `scripts/scrape_ij.js` - a plain Node/Playwright scraper that loads IJ's
  database page, waits out its Cloudflare challenge, and parses the incident
  list directly out of the page's own `data-*` attributes. No LLM calls of
  any kind are involved.

## Why IJ instead of open-ended web search

This tracker previously ran a weekly Claude-driven web search to find new
misuse stories on its own. The Institute for Justice already maintains a
better-curated, more complete version of that same dataset - identified
individuals, one entry per incident, each independently sourced - as part of
their Plate Privacy Project. Rather than duplicate that research with a
worse tool, this tracker now scrapes IJ's own database directly and adds
nothing IJ hasn't already documented. The full prior dataset (built from
web search) was cleared out rather than merged, since it overlapped heavily
with IJ's data and disagreed with it in places IJ's sourcing is more
reliable.

## How it stays current

A scheduled job re-scrapes IJ's database daily and rewrites `data/cases.json`
in full, diffing against the previous run by IJ's own internal incident ID
so `first_seen_at`/`last_seen_at` stay accurate and nothing is silently
dropped if an entry disappears from IJ's page (see `status` in SCHEMA.md).

## Data schema

`data/cases.json` is a flat array of incidents (`incidents[]`), each with a
normalized `classification` (stalking / non-law-enforcement-use /
other-misuse / error - IJ's own four categories) and zero or more
`outcomes` (fired, resigned, arrested, charged, convicted, sentenced, etc.),
keyword-matched against IJ's description text. See [`SCHEMA.md`](SCHEMA.md)
for the full field reference and the outcome-keyword table.

## Data quality / review model

Classification comes straight from IJ's own categorization. Outcome tagging
is deterministic keyword matching, not a verified fact independent of the
description - `outcome_matches[]` on each entry records the literal phrase
that triggered each tag, so a reviewer can sanity-check a tag without
re-reading the source article. Everything scraped lands as `verified: false`;
periodically review `data/run-log/` and spot-check entries against
`source_url`.

## Known limitations

- This tracker is only as complete as IJ's own database. IJ's database in
  turn depends on public reporting, so it's a documented floor, not a true
  total, the same limitation IJ itself notes.
- IJ does not publish a structured outcome field, so `outcomes[]` is this
  tracker's own keyword-based inference over IJ's description text and can
  miss or mis-tag edge cases - see SCHEMA.md.
- IJ's site sits behind a Cloudflare bot challenge. The scraper uses a
  stealth-patched headless browser to get past it; if IJ tightens that
  challenge, the scrape may start failing and will need attention.
