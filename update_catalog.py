#!/usr/bin/env python3
"""Brings catalog/ up to date with rentals the site has added or changed since
the last run, using the API's modified_after filter: a few requests a week
instead of the ~1,000 a full pass takes.

The site applies its changes in one batch each morning (around 9:25), and
moving a title to another shelf updates its modified time, so this also picks
up titles leaving New Arrival for their permanent shelf.

New rentals go to catalog/page0.json; changed ones are updated in place.
Their shelf fields are left for build_shelves.py to redo. The ids of new and
moved rentals are written to changed-ids.txt for scrape_shelves.py --ids,
along with any from earlier runs whose shelf is still unknown.
Term tables (locations.json, catalog-details/terms/) are fetched again only
when a rental has a term id they lack.

  --since YYYY-MM-DDTHH:MM:SS
                  start from this site-local time instead of the saved one
                  (needed on the first run)

Saves the newest modified time seen in catalog-updated.json.
"""
import glob, html, json, os, sys, time, urllib.parse, urllib.request
from merge_details import FIELDS, load_terms, names_for
from build_shelves import UA

API = 'https://www.moviemadness.org/wp-json/wp/v2/'
STATE, CHANGED = 'catalog-updated.json', 'changed-ids.txt'
ADDED = 'catalog/page0.json'   # numbered for build_shelves.py's sort; fetch_catalog.sh starts at page1
FETCH = 'id,slug,title,location,format,rating,date,genre,language,modified'
PAUSE = 0.4

def log(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)

def get(path, params):
    """JSON and total pages for one API request, retried three times."""
    url = API + path + '?' + urllib.parse.urlencode(params)
    for attempt in range(3):
        time.sleep(PAUSE if attempt == 0 else 5 * (attempt + 1))
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r), int(r.headers.get('X-WP-TotalPages') or 1), int(r.headers.get('X-WP-Total') or 0)
        except Exception as ex:
            log(f'  error {ex} on {url}')
    sys.exit(f'giving up on {url}')

def get_all(path, params):
    rows, page, pages = [], 1, 1
    while page <= pages:
        got, pages, _ = get(path, {**params, 'per_page': 100, 'page': page})
        rows += got
        page += 1
    return rows

def write_json(f, data):
    tmp = f + '.tmp'
    with open(tmp, 'w') as out:
        json.dump(data, out, ensure_ascii=False)
    os.replace(tmp, f)

def refresh_terms(changed):
    """Fetches the term tables again for any taxonomy with ids they don't have."""
    locs = {t['id'] for t in json.load(open('locations.json'))}
    if any(i not in locs for e in changed for i in e.get('location', [])):
        rows = get_all('location', {'_fields': 'id,count,description,name,slug'})
        write_json('locations.json', rows)
        log(f'locations.json fetched again: {len(rows)} terms')
    terms = load_terms(quiet=True)
    for tax in FIELDS:
        if any(i not in terms[tax] for e in changed for i in e.get(tax, [])):
            rows = get_all(tax, {'_fields': 'id,name,slug,parent,count'})
            for n in range(0, len(rows), 100):   # same layout as fetch_details.sh: date1.json, date2.json, ...
                write_json(f'catalog-details/terms/{tax}{n // 100 + 1}.json', rows[n:n + 100])
            log(f'{tax} terms fetched again: {len(rows)}')
    return load_terms(quiet=True), {t['id']: t['name'] for t in json.load(open('locations.json'))}

def main():
    since = sys.argv[sys.argv.index('--since') + 1] if '--since' in sys.argv else \
        json.load(open(STATE))['modified'] if os.path.exists(STATE) else None
    if not since:
        sys.exit('first run: pass --since with a time before the catalog was fetched')

    changed = get_all('rental', {'modified_after': since, 'orderby': 'modified', 'order': 'asc', '_fields': FETCH})
    log(f'{len(changed)} rentals changed since {since}')
    terms, loc_names = refresh_terms(changed)

    pages = {f: json.load(open(f)) for f in glob.glob('catalog/page*.json')}
    if ADDED not in pages:
        pages[ADDED] = []
    where = {e['id']: (f, n) for f, es in pages.items() for n, e in enumerate(es)}
    new, moved, edited = [], [], 0
    for c in changed:
        fields = {'id': c['id'], 'slug': c['slug'], 'title': c['title'],
                  'location': c['location'], 'location_names': [loc_names.get(i) for i in c['location']]}
        for tax, field in FIELDS.items():   # the API's "date" is the year taxonomy, not the post date
            fields[field] = names_for(c.get(tax, []), terms[tax])
        if c['id'] in where:
            f, n = where[c['id']]
            e = pages[f][n]
            if sorted(e.get('location', [])) != sorted(c['location']):
                moved.append(c['id'])
            elif all(e.get(k) == v for k, v in fields.items()):
                continue
            e.update(fields)
            edited += 1
        else:
            pages[ADDED].append(fields)
            where[c['id']] = (ADDED, len(pages[ADDED]) - 1)
            new.append(c['id'])
    for f, es in pages.items():
        if f != ADDED or es:
            write_json(f, es)
    log(f'{len(new)} new, {len(moved)} moved to another location, {edited - len(moved)} other edits')

    _, _, total = get('rental', {'per_page': 1, '_fields': 'id'})
    have = sum(len(es) for es in pages.values())
    log(f'site has {total} rentals, catalog {have}' + ('' if total == have else
        f': {have - total} more here, so some were removed' if have > total else f': {total - have} missing here'))

    # Keep earlier ids whose shelf is still unknown, in case their scrape didn't run.
    ids = dict.fromkeys(new + moved)
    if os.path.exists(CHANGED):
        for i in map(int, open(CHANGED).read().split()):
            f, n = where.get(i, (None, None))
            if f and not pages[f][n].get('shelf_complete'):
                ids[i] = None
    with open(CHANGED, 'w') as out:
        out.writelines(f'{i}\n' for i in ids)
    if changed:
        write_json(STATE, {'modified': max(c['modified'] for c in changed)})

if __name__ == '__main__':
    main()
