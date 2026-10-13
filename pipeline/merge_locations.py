"""Adds location term ids and names to the scraped catalog pages.

Reads catalog-loc/ (from fetch_locations.sh) and locations.json, then writes
`location` and `location_names` into every entry in catalog/, matched by id.
Only adds fields, so it is safe to re-run.
"""
import glob
import json
import os
from collections import Counter

here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
names = {t["id"]: t["name"] for t in json.load(open(os.path.join(here, "locations.json")))}

loc_by_id = {}
for f in glob.glob(os.path.join(here, "catalog-loc", "page*.json")):
    for e in json.load(open(f)):
        loc_by_id[e["id"]] = e.get("location") or []

stats = Counter()
unknown_terms = Counter()
for f in sorted(glob.glob(os.path.join(here, "catalog", "page*.json"))):
    entries = json.load(open(f))
    for e in entries:
        if e["id"] not in loc_by_id:
            stats["not in location pull"] += 1
            continue
        ids = loc_by_id[e["id"]]
        e["location"] = ids
        e["location_names"] = [names.get(i) for i in ids]
        for i in ids:
            if i not in names:
                unknown_terms[i] += 1
        stats["no location" if not ids else "one location" if len(ids) == 1 else "several locations"] += 1
    tmp = f + ".tmp"
    with open(tmp, "w") as out:
        json.dump(entries, out, ensure_ascii=False)
    os.replace(tmp, f)

print(f"location pull covered {len(loc_by_id)} entries")
for k, v in stats.most_common():
    print(f"  {k}: {v}")
if unknown_terms:
    print("term ids missing from locations.json:", dict(unknown_terms))
