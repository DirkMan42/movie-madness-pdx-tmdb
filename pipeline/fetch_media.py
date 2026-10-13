#!/usr/bin/env python3
"""Pages the whole catalog for each rental's cover image and description, which
the earlier passes didn't ask for (resumable; two small requests per page of
100: the listing, then one lookup of its image ids).

The covers are TMDB posters under their TMDB file names, so a rental's poster
name says which TMDB film or show the store matched it to; resolve_tmdb.py
turns the names into TMDB ids.

Saves catalog-media/pageN.json: id, poster (the TMDB file name, None without a
cover) and description (plain text). Once every page is in, writes `poster`
into catalog/. Descriptions stay in catalog-media/.

  --window HH:MM-HH:MM   as in scrape_shelves.py
"""
import datetime, glob, json, os
from scrape_shelves import deadline, log
from update_catalog import get, posters_for, text, write_json

def merge():
    posters = {r['id']: r['poster'] for f in glob.glob('catalog-media/page*.json') for r in json.load(open(f))}
    n = 0
    for f in glob.glob('catalog/page*.json'):
        es = json.load(open(f))
        for e in es:
            if e['id'] in posters:
                e['poster'] = posters[e['id']]
                n += bool(e['poster'])
        write_json(f, es)
    log(f'poster written to the catalog for {n} rentals; {len(posters) - n} have no cover')

def main():
    stop_at = deadline()
    os.makedirs('catalog-media', exist_ok=True)
    _, pages, total = get('rental', {'per_page': 100, '_fields': 'id'})
    log(f'{total} rentals on {pages} pages')
    requests = 1
    for page in range(1, pages + 1):
        f = f'catalog-media/page{page}.json'
        if os.path.exists(f):
            continue
        if stop_at and datetime.datetime.now() >= stop_at:
            log(f'stopping: reached {stop_at:%H:%M} at page {page}')
            return
        rows, _, _ = get('rental', {'per_page': 100, 'page': page, 'orderby': 'id', 'order': 'asc',
                                    '_fields': 'id,content,featured_media'})
        posters = posters_for(r['featured_media'] for r in rows)
        requests += 2
        write_json(f, [{'id': r['id'], 'poster': posters.get(r['featured_media']),
                        'description': text(r['content']['rendered'])} for r in rows])
        if page % 50 == 0:
            log(f'  page {page} of {pages}, {requests} requests')
    log(f'all {pages} pages fetched; {requests} requests this run')
    merge()

if __name__ == '__main__':
    main()
