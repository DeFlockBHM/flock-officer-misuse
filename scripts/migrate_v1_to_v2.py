#!/usr/bin/env python3
"""One-time migration: flat v1 cases.json -> v2 schema with incidents + cases.

v2 adds an incident/case split so multi-officer sweeps (e.g. Georgia) can be
tracked as a single incident with a reported_count, even before every
officer involved has been publicly named. Solo cases get an auto-generated
1:1 incident wrapper for schema uniformity (every case has a parent_incident_id).
"""
import hashlib
import json
import re
from datetime import datetime, timezone

IN_PATH = "data/cases.json"
OUT_PATH = "data/cases.json"

NOW = datetime.now(timezone.utc).isoformat()

# Known multi-officer records from the v1 seed that represent a single sweep/
# incident with multiple already-named individuals. Everything else is treated
# as a solo case (1 person = 1 incident).
MULTI_OFFICER_IDS = {
    "albany-ga-5officers-2026",
    "richmond-county-ga-4deputies-2026",
    "cherokee-county-ga-3deputies-2026",
    "fayetteville-ga-3officers-2026",
    "alabama-2officers-2026",
    "lynch-echeverry-2026-greer-sc",
}


def content_hash(case):
    material = "|".join([
        case.get("allegation_summary", ""),
        case.get("outcome_detail", ""),
        case.get("status", ""),
    ])
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def split_names(name_field):
    # "A; B; C" -> ["A", "B", "C"]; also handles "Unnamed (3 officers)" as a
    # single placeholder entry (not split).
    if ";" in name_field:
        return [n.strip() for n in name_field.split(";")]
    return [name_field.strip()]


def make_incident(incident_id, state, agency, reported_count, identified_count,
                   date_text, source_urls, status):
    return {
        "id": incident_id,
        "state": state,
        "agencies": [agency] if agency else [],
        "reported_count": reported_count,
        "identified_count": identified_count,
        "date_range": {"start": date_text, "end": date_text},
        "status": status,  # fully_identified | partially_identified | unidentified
        "source_urls": source_urls or [],
        "notes": "",
        "first_seen_at": NOW,
        "last_seen_at": NOW,
        "verified": False,
    }


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "unnamed"


def main():
    with open(IN_PATH) as f:
        old = json.load(f)

    incidents = []
    new_cases = []

    for c in old["cases"]:
        names = split_names(c["name"])
        is_multi = c["id"] in MULTI_OFFICER_IDS and len(names) > 1
        is_placeholder = names[0].lower().startswith("unnamed")

        if is_multi:
            incident_id = c["id"] + "-incident"
            incidents.append(make_incident(
                incident_id=incident_id,
                state=c.get("state"),
                agency=c.get("agency"),
                reported_count=len(names),
                identified_count=0 if is_placeholder else len(names),
                date_text=c.get("last_updated") or "",
                source_urls=c.get("sources", []),
                status="unidentified" if is_placeholder else "fully_identified",
            ))
            if is_placeholder:
                # Names not public yet -- keep as a single unnamed placeholder
                # case linked to the incident rather than fabricating N entries.
                new_case = dict(c)
                new_case["parent_incident_id"] = incident_id
                new_case["content_hash"] = content_hash(c)
                new_case["first_seen_at"] = NOW
                new_case["last_seen_at"] = NOW
                new_case["verified"] = False
                new_cases.append(new_case)
            else:
                for person_name in names:
                    new_case = dict(c)
                    new_case["id"] = f"{c['id']}-{slugify(person_name)}"
                    new_case["name"] = person_name
                    new_case["parent_incident_id"] = incident_id
                    new_case["content_hash"] = content_hash(c)
                    new_case["first_seen_at"] = NOW
                    new_case["last_seen_at"] = NOW
                    new_case["verified"] = False
                    new_cases.append(new_case)
        else:
            # Solo case -> auto-generated 1:1 incident wrapper.
            incident_id = c["id"] + "-incident"
            incidents.append(make_incident(
                incident_id=incident_id,
                state=c.get("state"),
                agency=c.get("agency"),
                reported_count=1,
                identified_count=0 if is_placeholder else 1,
                date_text=c.get("last_updated") or "",
                source_urls=c.get("sources", []),
                status="unidentified" if is_placeholder else "fully_identified",
            ))
            new_case = dict(c)
            new_case["parent_incident_id"] = incident_id
            new_case["content_hash"] = content_hash(c)
            new_case["first_seen_at"] = NOW
            new_case["last_seen_at"] = NOW
            new_case["verified"] = False
            new_cases.append(new_case)

    new_data = {
        "schema_version": 2,
        "last_updated": NOW[:10],
        "notes": old.get("notes", ""),
        "aggregate_trackers": old.get("aggregate_trackers", []),
        "incidents": incidents,
        "cases": new_cases,
    }

    with open(OUT_PATH, "w") as f:
        json.dump(new_data, f, indent=2)
        f.write("\n")

    print(f"Migrated {len(old['cases'])} v1 cases -> {len(incidents)} incidents, {len(new_cases)} v2 cases")


if __name__ == "__main__":
    main()
