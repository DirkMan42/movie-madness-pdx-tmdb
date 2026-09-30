#!/usr/bin/env python3
"""Adds format, rating, year, genre and language names to catalog/page*.json from
the pass fetch_details.sh saved in catalog-details/. Matched by entry id;
re-runnable. Each field is a list of names, since an entry can have several
(or none). Genre and format names include their parent: "Horror > Slasher".

The API calls the year taxonomy "date"; it's saved here as "year".
Ratings NR, N/A and N/ are saved as N/R, the one the search filter offers.
"""
import glob, html, json
from collections import Counter

FIELDS = {'format': 'format', 'rating': 'rating', 'date': 'year', 'genre': 'genre', 'language': 'language'}

terms = {}
for tax in FIELDS:
    rows = [t for f in sorted(glob.glob(f'catalog-details/terms/{tax}*.json')) for t in json.load(open(f))]
    by_id = {t['id']: t for t in rows}
    def full(t):
        name = html.unescape(t['name'])
        p = by_id.get(t.get('parent') or 0)
        return f'{full(p)} > {name}' if p else name
    terms[tax] = {t['id']: full(t) for t in rows}
    print(f'{tax}: {len(rows)} terms')

# The site has several spellings of "not rated"; its search filter offers only N/R.
NOT_RATED = {'NR', 'N/A', 'N/'}
terms['rating'] = {i: 'N/R' if n in NOT_RATED else n for i, n in terms['rating'].items()}

details = {e['id']: e for f in glob.glob('catalog-details/page*.json') for e in json.load(open(f))}
pages = glob.glob('catalog/page*.json')
seen, unknown, counts = set(), Counter(), {v: Counter() for v in FIELDS.values()}
for f in pages:
    es = json.load(open(f))
    for e in es:
        d = details.get(e['id'])
        if not d:
            continue
        seen.add(e['id'])
        for tax, field in FIELDS.items():
            names = []
            for i in d.get(tax, []):
                if i in terms[tax]:
                    if terms[tax][i] not in names:   # N/R and NR on one entry → one N/R
                        names.append(terms[tax][i])
                else:
                    unknown[tax] += 1
            e[field] = names
            counts[field][len(names)] += 1
    json.dump(es, open(f, 'w'))

catalog_ids = {e['id'] for f in pages for e in json.load(open(f))}
print(f'entries updated: {len(seen)} of {len(catalog_ids)}')
print(f'in the catalog but not the new pass: {len(catalog_ids - set(details))}')
print(f'in the new pass but not the catalog: {len(set(details) - catalog_ids)}')
print(f'term ids not in the tables: {dict(unknown)}')
for field, c in counts.items():
    print(f'{field}: entries by number of values {dict(sorted(c.items()))}')
ratings = Counter(r for f in pages for e in json.load(open(f)) for r in e.get('rating', []))
print(f'ratings: {dict(ratings.most_common())}')
