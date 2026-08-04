# Data schema (v2)

`data/cases.json` has this top-level shape:

```json
{
  "schema_version": 2,
  "last_updated": "2026-08-03",
  "notes": "...",
  "aggregate_trackers": [ ... ],
  "incidents": [ ... ],
  "cases": [ ... ]
}
```

## Why incidents and cases are separate

Multi-officer sweeps (Georgia's audit-driven arrests are the clearest example)
are often reported as a **count before names**: "22 officers arrested" comes
out well before the individuals are publicly identified, and names then trickle
in over the following days/weeks. If every named article were treated as an
independent signal, the tracker would eventually either double-count someone
who was already part of the reported total, or fail to recognize a genuinely
new, unrelated case in the same state.

To handle this, every `case` (a named or "Unnamed (role)" individual) is linked
to a parent `incident` (the reported enforcement event) via
`parent_incident_id`. This applies uniformly — even a solo, single-officer case
gets an auto-generated 1:1 incident wrapper — so the schema never branches on
"is this a sweep or not," and a solo case that later turns out to be part of a
larger sweep doesn't require restructuring.

## `incidents[]`

| Field | Type | Description |
|---|---|---|
| `id` | string | Stable slug, e.g. `ga-albany-sweep-2026-07` |
| `state` | string | Two-letter state code |
| `agencies` | array of strings | One or more agencies involved |
| `reported_count` | int | How many officers reporting says are involved |
| `identified_count` | int | How many are named/linked so far |
| `date_range` | `{start, end}` | ISO dates bounding the reported event |
| `status` | string | `unidentified` \| `partially_identified` \| `fully_identified` |
| `source_urls` | array of strings | Source article URLs |
| `notes` | string | Free text, e.g. auto-generation notes |
| `first_seen_at` / `last_seen_at` | ISO datetime | Append-only provenance — `first_seen_at` is never overwritten |
| `verified` | bool | Defaults to `false`. Every auto-written or auto-linked incident starts unverified; a human should review and flip this. |

If `identified_count` exceeds `reported_count`, that's a signal something's
wrong (over-linking, or `reported_count` itself needs correcting) — the weekly
script flags this explicitly in its log rather than silently letting the
numbers diverge.

## `cases[]`

| Field | Type | Description |
|---|---|---|
| `id` | string | Stable slug, e.g. `lastname-year-city-st` |
| `parent_incident_id` | string | **Required.** Always points to a real `incidents[].id` |
| `name` | string | Full name, or `"Unnamed (role)"` if not yet public |
| `agency` | string | Department/agency |
| `state` | string | Two-letter state code |
| `role` | string | Job title |
| `misuse_type` | string | `romantic_stalking` \| `personal_use` \| `corruption` \| `other` \| `mixed` |
| `allegation_summary` | string | 1–2 sentence factual summary |
| `outcomes` | array of strings | e.g. `["fired", "arrested"]` |
| `outcome_detail` | string | Specific dates/charges/sentences; also where the script notes any uncertainty about an incident link |
| `status` | string | e.g. `charged`, `convicted`, `under_investigation` |
| `last_updated` | ISO date | Most recent known development |
| `sources` | array of strings | Source URLs |
| `content_hash` | string | `sha256:` hash of `allegation_summary + outcome_detail + status`, recomputed on every update — lets you detect at a glance whether a case's substantive facts changed between runs, without needing to diff full text or archive the source |
| `first_seen_at` / `last_seen_at` | ISO datetime | Same append-only convention as incidents |
| `verified` | bool | Defaults to `false`; flipped to `true` on manual review |

## `aggregate_trackers[]`

External running counts (e.g. Institute for Justice's stalking tally,
Georgia's cumulative arrest count) that should be **checked against, not
summed with**, the individual incident/case data — they overlap only
partially with each other and with this dataset.

## Deliberate omissions

This schema does **not** snapshot source articles via the Wayback Machine
(unlike the [deflocked-municipalities](https://github.com/DeFlockBHM/deflocked-municipalities)
project this was modeled on). Source URLs are stored as-is; if link rot
becomes a problem later, that's a reasonable addition to revisit.

## Review workflow

Nothing the weekly script writes is `verified: true`. The intended workflow
is: the script auto-links and auto-creates with its best judgment (including
guessing at incident links when it's not fully confident — noting that
uncertainty in `outcome_detail`), and a human periodically reviews
`data/weekly-log/` entries and anything with `verified: false` — especially
anything the script explicitly flagged (identified_count exceeding
reported_count) — and corrects/confirms in `data/cases.json` directly.
