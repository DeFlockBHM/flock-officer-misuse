#!/usr/bin/env python3
"""
Weekly Flock Safety misuse tracker updater (schema v2).

Loads the existing dataset (data/cases.json — incidents[] + cases[]), asks
Claude (with the web_search tool) to find developments from the last ~7-10
days, and merges results:

  - New multi-officer sweeps become an `incident` (reported_count may exceed
    identified_count if names aren't public yet).
  - Newly-named individuals are linked to an existing open incident when the
    model finds a plausible match (same state/agency/date window, and the
    incident isn't already fully identified); otherwise a new 1:1 incident is
    auto-generated so every case always has a parent_incident_id.
  - All new/updated cases and incidents are written with verified: false —
    auto-linking is a claim, not a fact, and should get human review later.
  - A content_hash is stored per case (hash of the mutable summary fields) so
    future runs can cheaply detect when a case's known facts have changed,
    without needing to re-fetch or archive the source article.

Requires the ANTHROPIC_API_KEY environment variable (GitHub Actions secret).
"""
import hashlib
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES_PATH = os.path.join(REPO_ROOT, "data", "cases.json")
LOG_DIR = os.path.join(REPO_ROOT, "data", "weekly-log")

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
MAX_TOKENS = 8000

SYSTEM_PROMPT = """You are a research assistant maintaining a factual, well-sourced \
tracker of law enforcement officers/personnel who have been fired, forced to resign, \
arrested, charged, or convicted specifically for misusing Flock Safety ALPR \
(automated license plate reader) technology, in the United States.

The dataset has two linked record types:

INCIDENTS represent a reported enforcement event, which may involve one or many \
officers, and may be reported before every officer's name is public. Fields:
  id, state, agencies (array), reported_count (how many officers the reporting \
  says are involved), identified_count (how many are named so far), date_range, \
  status ("unidentified" | "partially_identified" | "fully_identified"), source_urls.

CASES represent one named (or "Unnamed (role)" placeholder) individual, always \
linked to an incident via parent_incident_id.

You will be given the CURRENT incidents and cases (trimmed). Your job is to search \
the web for developments in roughly the last 7-10 days ONLY, and identify:

  1. Brand-new incidents (a new sweep, or a new solo arrest/firing/conviction not \
     already in the dataset).
  2. Newly-named individuals who plausibly belong to an EXISTING incident that isn't \
     fully identified yet (match on state + agency + approximate date + the incident \
     still having identified_count < reported_count). Link these via parent_incident_id \
     and DO NOT create a new incident for them -- reference the existing incident id.
     If you are not confident about the link, still make your best-guess link rather \
     than skipping it (this project auto-links with verified:false and reviews \
     later) -- but note your uncertainty in the case's outcome_detail field.
  3. Status changes to existing cases or incidents (e.g. arrest -> conviction, \
     identified_count increasing, charges dropped). Reference the existing id.

If nothing new is found in the time window, say so explicitly -- do not pad the \
response with things already in the dataset, and do not invent or guess at names, \
charges, or outcomes not reported by a source.

Respond in two parts, in this exact order:

PART 1 -- a concise human-readable markdown summary of what's new (or "No new \
developments found this week"), with inline source citations as plain URLs.

PART 2 -- a fenced ```json code block containing ONE object with two arrays, using \
this exact schema (omit fields you don't know, but always include the id fields and \
status):

{
  "new_incidents": [
    {
      "id": "state-shortdesc-year-month",
      "state": "XX",
      "agencies": ["Agency Name"],
      "reported_count": 3,
      "identified_count": 0,
      "date_range": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
      "status": "unidentified",
      "source_urls": ["https://..."]
    }
  ],
  "new_or_updated_cases": [
    {
      "id": "lastname-year-city-st",
      "parent_incident_id": "id-of-new-or-existing-incident",
      "name": "Full Name or Unnamed (role)",
      "agency": "Department/Agency",
      "state": "XX",
      "role": "Officer/Detective/etc",
      "misuse_type": "romantic_stalking | personal_use | corruption | other | mixed",
      "allegation_summary": "One or two sentence factual summary",
      "outcomes": ["fired", "arrested", "convicted", "resigned", "charged"],
      "outcome_detail": "Specific dates, charges, sentence if known; note any linking uncertainty here",
      "status": "charged | convicted | fired_no_charges_yet | resigned_no_charges_known | under_investigation | no_crime_found",
      "last_updated": "YYYY-MM-DD",
      "sources": ["https://..."]
    }
  ]
}

If there's nothing new, output {"new_incidents": [], "new_or_updated_cases": []}.

Follow standard copyright practice: paraphrase everything, never quote more than a \
short phrase from any source, and cite sources as plain URLs (not embedded quotes).
"""


def load_dataset():
    with open(CASES_PATH, "r") as f:
        return json.load(f)


def save_dataset(data):
    with open(CASES_PATH, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def content_hash(case):
    material = "|".join([
        case.get("allegation_summary", ""),
        case.get("outcome_detail", ""),
        case.get("status", ""),
    ])
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def call_claude(dataset):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    trimmed_incidents = [
        {
            "id": i["id"],
            "state": i["state"],
            "agencies": i["agencies"],
            "reported_count": i["reported_count"],
            "identified_count": i["identified_count"],
            "date_range": i["date_range"],
            "status": i["status"],
        }
        for i in dataset["incidents"]
    ]
    trimmed_cases = [
        {
            "id": c["id"],
            "parent_incident_id": c.get("parent_incident_id"),
            "name": c["name"],
            "agency": c["agency"],
            "state": c["state"],
            "status": c["status"],
        }
        for c in dataset["cases"]
    ]

    user_message = (
        "Current incidents:\n" + json.dumps(trimmed_incidents, indent=2)
        + "\n\nCurrent cases:\n" + json.dumps(trimmed_cases, indent=2)
        + f"\n\nToday's date is {date.today().isoformat()}. Search for developments "
        "in the Flock Safety officer-misuse story from roughly the last 7-10 days "
        "and report per the instructions."
    )

    body = json.dumps(
        {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_message}],
            "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=300) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    text_blocks = [b["text"] for b in payload.get("content", []) if b.get("type") == "text"]
    return "\n".join(text_blocks)


def split_response(full_text):
    match = re.search(r"```json\s*(\{.*?\})\s*```", full_text, re.DOTALL)
    if not match:
        return full_text.strip(), {"new_incidents": [], "new_or_updated_cases": []}

    summary = full_text[: match.start()].strip()
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        parsed = {"new_incidents": [], "new_or_updated_cases": []}
    parsed.setdefault("new_incidents", [])
    parsed.setdefault("new_or_updated_cases", [])
    return summary, parsed


def merge(dataset, parsed):
    now = datetime.now(timezone.utc).isoformat()
    incidents_by_id = {i["id"]: i for i in dataset["incidents"]}
    cases_by_id = {c["id"]: c for c in dataset["cases"]}

    added_incidents, added_cases, updated_cases, flagged = [], [], [], []

    for inc in parsed["new_incidents"]:
        iid = inc.get("id")
        if not iid:
            continue
        if iid in incidents_by_id:
            incidents_by_id[iid].update({k: v for k, v in inc.items() if v is not None})
            incidents_by_id[iid]["last_seen_at"] = now
        else:
            inc.setdefault("verified", False)
            inc["first_seen_at"] = now
            inc["last_seen_at"] = now
            dataset["incidents"].append(inc)
            incidents_by_id[iid] = inc
            added_incidents.append(iid)

    for case in parsed["new_or_updated_cases"]:
        cid = case.get("id")
        if not cid:
            continue

        parent_id = case.get("parent_incident_id")
        # If the referenced incident doesn't exist at all, auto-generate a 1:1
        # incident wrapper so the case is never orphaned (schema invariant:
        # every case has a parent_incident_id pointing at a real incident).
        if parent_id and parent_id not in incidents_by_id:
            auto_incident = {
                "id": parent_id,
                "state": case.get("state"),
                "agencies": [case.get("agency")] if case.get("agency") else [],
                "reported_count": 1,
                "identified_count": 1,
                "date_range": {
                    "start": case.get("last_updated", ""),
                    "end": case.get("last_updated", ""),
                },
                "status": "fully_identified",
                "source_urls": case.get("sources", []),
                "notes": "Auto-generated 1:1 incident wrapper for a solo case.",
                "first_seen_at": now,
                "last_seen_at": now,
                "verified": False,
            }
            dataset["incidents"].append(auto_incident)
            incidents_by_id[parent_id] = auto_incident
            added_incidents.append(parent_id)
        elif parent_id in incidents_by_id and cid not in cases_by_id:
            # Linking a newly-named person into an existing incident: bump
            # identified_count and flag for review if this pushes past the
            # reported total -- that means either the link is wrong or the
            # reported_count itself needs updating.
            inc = incidents_by_id[parent_id]
            inc["identified_count"] = inc["identified_count"] + 1
            if inc["identified_count"] > inc["reported_count"]:
                flagged.append(f"{cid} pushes {parent_id} identified_count ({inc['identified_count']}) "
                                f"past reported_count ({inc['reported_count']}) -- needs manual review")
            inc["status"] = (
                "fully_identified" if inc["identified_count"] >= inc["reported_count"]
                else "partially_identified"
            )
            inc["last_seen_at"] = now
            inc["verified"] = False  # re-open for review since it just changed

        if cid in cases_by_id:
            cases_by_id[cid].update({k: v for k, v in case.items() if v is not None})
            cases_by_id[cid]["content_hash"] = content_hash(cases_by_id[cid])
            cases_by_id[cid]["last_seen_at"] = now
            cases_by_id[cid]["verified"] = False
            updated_cases.append(cid)
        else:
            case["content_hash"] = content_hash(case)
            case["first_seen_at"] = now
            case["last_seen_at"] = now
            case["verified"] = False
            dataset["cases"].append(case)
            cases_by_id[cid] = case
            added_cases.append(cid)

    return added_incidents, added_cases, updated_cases, flagged


def main():
    dataset = load_dataset()
    full_text = call_claude(dataset)
    summary, parsed = split_response(full_text)

    added_incidents, added_cases, updated_cases, flagged = merge(dataset, parsed)
    today = date.today().isoformat()
    dataset["last_updated"] = today
    save_dataset(dataset)

    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"{today}.md")
    with open(log_path, "w") as f:
        f.write(f"# Flock Safety Misuse Tracker — Weekly Update ({today})\n\n")
        f.write(summary + "\n\n")
        if added_incidents:
            f.write(f"**New incidents:** {', '.join(added_incidents)}\n\n")
        if added_cases:
            f.write(f"**New cases:** {', '.join(added_cases)}\n\n")
        if updated_cases:
            f.write(f"**Updated cases:** {', '.join(updated_cases)}\n\n")
        if flagged:
            f.write("**Flagged for manual review:**\n")
            for msg in flagged:
                f.write(f"- {msg}\n")
            f.write("\n")
        if not (added_incidents or added_cases or updated_cases):
            f.write("_No structured changes this run._\n")
        f.write(
            f"\n---\n_Generated {datetime.now(timezone.utc).isoformat()} "
            f"by scripts/update_tracker.py using model `{MODEL}`._\n"
        )

    print(f"Wrote {log_path}")
    print(f"New incidents: {added_incidents}")
    print(f"New cases: {added_cases}")
    print(f"Updated cases: {updated_cases}")
    if flagged:
        print(f"FLAGGED FOR REVIEW: {flagged}")


if __name__ == "__main__":
    main()
