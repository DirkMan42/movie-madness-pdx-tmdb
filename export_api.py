#!/usr/bin/env python3
"""Writes the catalog's rentals by TMDB id as small static JSON files, for
publishing with GitHub Pages so the userscript can look a film up by the TMDB
id on its Letterboxd page: one request, no searching.

  export_api.py [DIR]    default api/

DIR/tmdb/movie/NNN.json and DIR/tmdb/tv/NNN.json hold every TMDB id whose last
three digits are NNN (id % 1000, zero-padded), so a file is a few KB and all
2,000 exist, even if empty:

  {"603": [{"id": 12345, "slug": "matrix-the-dvd", "title": "Matrix, The (DVD)",
            "format": "DVD", "shelf": "Sci-Fi", "display": "Staff Picks",
            "match": "poster"}, ...]}

`shelf` is the permanent shelf and `display` a temporary one (New Arrival,
Staff Picks, ...); either is left out when not known. `match` is how the id
was found (resolve_tmdb.py's tmdb_source). A rental's page is
https://www.moviemadness.org/?rental=<slug>.

DIR/index.json has the counts, the time of the newest change on the site
that the files include, and the notice on whose data this is. Only files whose contents changed are written.
"""
import glob, html, json, os, sys

SHARDS = 1000
NOTICE = ('Catalog listings are the property of Movie Madness (moviemadness.org); this is an unaffiliated '
          'fan project, not endorsed by or connected with Movie Madness. This product uses the TMDB API but '
          'is not endorsed or certified by TMDB. The data is not covered by the code\'s MIT license; reuse '
          'is subject to the terms of Movie Madness and TMDB.')
FORMAT_ORDER = ['4K UHD', 'Blu-Ray 3D', 'Blu-Ray', 'DVD', 'DVD-R', 'VHS', 'Book']

def write_if_changed(f, data):
    body = json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n'
    if os.path.exists(f) and open(f).read() == body:
        return 0
    os.makedirs(os.path.dirname(f), exist_ok=True)
    with open(f + '.tmp', 'w') as out:
        out.write(body)
    os.replace(f + '.tmp', f)
    return 1

def rental(e):
    r = {'id': e['id'], 'slug': e['slug'], 'title': html.unescape(e['title']['rendered']),
         'format': (e['format'] or [None])[0], 'shelf': e.get('shelf'),
         'display': e.get('temporary_shelf'), 'match': e['tmdb_source']}
    return {k: v for k, v in r.items() if v is not None}

def main():
    out = sys.argv[1] if len(sys.argv) > 1 else 'api'
    shards = {(kind, n): {} for kind in ('movie', 'tv') for n in range(SHARDS)}
    rentals = 0
    for f in glob.glob('catalog/page*.json'):
        for e in json.load(open(f)):
            if e.get('tmdb'):
                kind, i = e['tmdb'].split('/')
                shards[kind, int(i) % SHARDS].setdefault(int(i), []).append(rental(e))
                rentals += 1
    order = {f: n for n, f in enumerate(FORMAT_ORDER)}
    written = 0
    for (kind, n), ids in shards.items():
        for rs in ids.values():
            rs.sort(key=lambda r: (order.get(r.get('format'), len(order)), r['id']))
        written += write_if_changed(f'{out}/tmdb/{kind}/{n:03}.json', {str(i): ids[i] for i in sorted(ids)})
    state = 'catalog-updated.json'
    counts = {kind: sum(len(ids) for (k, _), ids in shards.items() if k == kind) for kind in ('movie', 'tv')}
    written += write_if_changed(f'{out}/index.json', {
        'updated': json.load(open(state))['modified'] if os.path.exists(state) else None,
        'rentals': rentals, 'movie': counts['movie'], 'tv': counts['tv'], 'shards': SHARDS,
        'files': 'tmdb/{movie|tv}/{id % shards, 3 digits}.json', 'notice': NOTICE})
    print(f'api: {rentals} rentals under {counts["movie"]} films and {counts["tv"]} shows; {written} files written')

if __name__ == '__main__':
    main()
