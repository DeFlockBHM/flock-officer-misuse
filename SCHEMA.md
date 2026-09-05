# Data schema (v3)

`data/cases.json` has this top-level shape:

```json
{
  "schema_version": 3,
  "generated_at": "2026-09-05T00:00:00Z",
  "source_url": "https://ij.org/the-ij-database-of-alpr-abuse/",
  "source_name": "Institute for Justice - IJ Database of ALPR Abuse",
  "count": 0,
  "incidents": [ ... ]
}
```

## Why this replaced the v1/v2 incidents+cases split

The previous schema split reported sweeps (`incidents[]`, a count before names)
from named individuals (`cases[]`), to handle stories like "22 officers
arrested" landing before anyone was identified. That problem is specific to
tracking breaking news via LLM web search. The Institute for Justice's ALPR
abuse database (the [Plate Privacy Project](https://ij.org/the-ij-database-of-alpr-abuse/))
already does the identification work and publishes one entry per incident,
each with a stable ID, so the sweep/individual distinction is no longer
something this tracker needs to model itself. Every prior entry was cleared
out rather than migrated, since IJ's database and the old LLM-search dataset
overlapped heavily and disagreed in places on details neither could source
as well as IJ's own page.

## Where the data comes from

A plain HTTP scraper (`scripts/scrape_ij.js`, Node + Playwright) loads
`https://ij.org/the-ij-database-of-alpr-abuse/` daily, waits out the page's
Cloudflare challenge, and parses the rendered incident list directly from
`data-*` attributes IJ already puts on each `<article>` element (id, city,
state, category, manufacturer, date, description, source link) - there is no
free-text extraction or LLM involved.

IJ's database covers every ALPR vendor it has documented abuse for (Flock,
Rekor, Vigilant, Guardian, NDI, and some entries where the vendor isn't
specified), not just Flock. This tracker keeps the full set rather than
filtering it down - see `manufacturer` / `is_flock` below - since the
misuse/outcome patterns are useful across vendors and dropping non-Flock
rows would throw away real data for no benefit. Filter to `is_flock: true`
downstream if you only want the Flock subset.

IJ's page does not publish a personnel-outcome field, so `outcomes[]` (see
below) is derived from the incident description via deterministic keyword
matching - not an LLM judgment call. It will sometimes under- or over-tag;
treat it as a best-effort index into the description text, not a verified
fact independent of it.

## `incidents[]`

| Field | Type | Description |
|---|---|---|
| `id` | string | Stable slug: `<state>-<city>-<ij_source_id>` |
| `ij_source_id` | string | IJ's own internal incident ID (`data-alpr-incident`) - the real identity key; the slug is derived from it for readability but `ij_source_id` is what diffing keys off |
| `title` | string | IJ's own title, e.g. `"Clayton County, GA - September 2026"` |
| `location` | `{city, state, state_name}` | `state` is lowercase full state name as IJ encodes it (their site has no 2-letter codes); kept as-is rather than invented |
| `date` | `{text, iso}` | `text` is IJ's own display date (usually month/year); `iso` is `data-date`, which IJ documents as "when the misuse began, if known, or when it was first publicly reported" |
| `classification` | string | Normalized enum, see **Classification types** below |
| `classification_raw` | string | IJ's own category label, e.g. `"Non Law-Enforcement Use"` |
| `manufacturer` | string | IJ's normalized vendor slug: `flock`, `rekor`, `vigilant`, `guardian`, `ndi`, or `unspecified` |
| `manufacturer_name` | string | IJ's display name for the vendor, e.g. `"Flock"`, `"Unspecified"` |
| `is_flock` | bool | `true` iff `manufacturer === "flock"` - convenience field so consumers can filter to the Flock subset without checking the raw slug |
| `description` | string | IJ's own one-sentence summary - already short, not full article text, so no separate excerpt/copyright handling is needed here (contrast `deflocked-municipalities`, which fetches and excerpts full articles itself) |
| `source_url` | string | The "Original source" link IJ attaches to the entry (a news article, court filing, or public-records release) |
| `outcomes` | array of strings | Zero or more entries from the **Outcome types** enum below, keyword-matched against `description` |
| `outcome_matches` | array of strings | The literal substrings that triggered each outcome tag, for auditability - lets a human check the keyword match wasn't spurious without re-reading IJ's site |
| `content_hash` | string | `sha256:` of `classification_raw + description + source_url + date.iso`, recomputed every run - detects real changes vs. a no-op rescrape |
| `first_seen_at` / `last_seen_at` | ISO datetime | Append-only provenance; `first_seen_at` never overwritten |
| `status` | string | `active` (currently present in IJ's database) or `removed_from_source` (was present in a prior run, no longer found - flagged, never silently dropped) |
| `verified` | bool | Always `false` from the scraper; reserved for optional manual QA, same convention as prior schema versions |

## Classification types

Taken directly from IJ's own four categories (`data-type` on each entry):

| `classification` | IJ's label | Meaning |
|---|---|---|
| `stalking` | Stalking | ALPR data used to track a romantic partner, ex-partner, or other personal target |
| `non_law_enforcement_use` | Non Law-Enforcement Use | Access or searches outside any legitimate law-enforcement purpose (personal curiosity, favors, unauthorized sharing, etc.) that isn't stalking specifically |
| `other_misuse` | Other Misuse | Misuse that doesn't fit the above (e.g. searches without a case number, policy violations) |
| `error` | Error | System/process failure rather than deliberate misuse (false-positive stop, wrong vehicle, technical malfunction) |

## Outcome types

Keyword-matched against `description`, case-insensitive. An entry can carry
multiple outcomes (e.g. `["arrested", "charged"]`) or none if nothing in the
description matches (common for `error`-type entries with no personnel
consequence, e.g. a wrongful stop with no disciplinary follow-up reported).

| `outcome` | Trigger keywords (examples) |
|---|---|
| `fired` | fired, terminated |
| `resigned` | resigned |
| `retired` | retired |
| `arrested` | arrested |
| `charged` | charged, indicted |
| `pleaded_guilty` | pled guilty, pleaded guilty |
| `convicted` | convicted |
| `sentenced` | sentenced, sentence |
| `suspended` | suspended |
| `administrative_leave` | administrative leave, placed on leave, put on leave |
| `demoted` | demoted |
| `disciplined` | disciplinary action, corrective action, reprimand |
| `access_revoked` | access revoked, revoked access, access was suspended |
| `under_investigation` | under investigation, investigation is ongoing, being investigated |
| `no_action_reported` | Added when none of the above match and the description doesn't otherwise imply an open/ongoing status - i.e. the entry describes what happened but reports no consequence |

`outcome_matches[]` records which literal phrase fired for each tag, so a
reviewer can spot-check a tag against the actual sentence without needing to
click through to `source_url`.

## Deliberate omissions

- No Wayback Machine archiving (same decision as v1/v2 - see prior schema
  notes; IJ's own site is the canonical source and IJ itself credits and
  links the original article, so link rot risk is lower here than for
  `deflocked-municipalities`).
- No `aggregate_trackers[]` array. That field existed to reconcile this
  dataset against IJ's own running tallies; now that IJ's database *is* the
  source, there's nothing external left to reconcile against.
- No LLM/Claude API calls anywhere in the scraper. Classification and
  outcome tagging are both deterministic (IJ's own category attribute, and
  keyword matching, respectively).
