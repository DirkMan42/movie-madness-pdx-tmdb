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

DIR/unmatched.json lists the rentals with no TMDB id, by rental id, with the
year and language that might help find one (null when the store gives none;
several languages are joined with ", "), and `rejected`, the id that was
found and dropped because its titles are nothing like the rental's:

  [{"id": 27583, "slug": "...", "title": "Kiss Me Quick / House On Bare Mountain
    (Special Edition DVD)", "format": "DVD", "shelf": "Adult Theme > Something
    Weird", "year": "1962", "language": "English"}, ...]

DIR/index.json has the counts, the time of the newest change on the site
that the files include, and the notice on whose data this is. Only files
whose contents changed are written.

Nothing is written, and it exits with an error, when the catalog has no
rentals with an id or a tenth fewer than DIR/index.json says were there
before: more likely a broken run than a real change. --force writes anyway.
"""
import glob, html, json, os, re, sys

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

def title_format(title):
    """The format named last in a title's parentheses, for the few rentals the store gave none."""
    named = [f for part in re.findall(r'\(([^)]*)\)', title) for f in FORMAT_ORDER
             if re.sub(r'\W', '', f).lower() == re.sub(r'\W', '', part).lower()]
    return named[-1] if named else None

def rental(e):
    title = html.unescape(e['title']['rendered'])
    r = {'id': e['id'], 'slug': e['slug'], 'title': title,
         'format': (e['format'] or [title_format(title)])[0], 'shelf': e.get('shelf'),
         'display': e.get('temporary_shelf'), 'match': e['tmdb_source']}
    return {k: v for k, v in r.items() if v is not None}

def unmatched(e):
    r = rental({**e, 'tmdb_source': None})
    r['year'] = (e.get('year') or [None])[0]
    r['language'] = ', '.join(e.get('language') or []) or None
    if e.get('tmdb_rejected'):
        r['rejected'] = e['tmdb_rejected']
    return r

def main():
    args = [a for a in sys.argv[1:] if a != '--force']
    out = args[0] if args else 'api'
    shards = {(kind, n): {} for kind in ('movie', 'tv') for n in range(SHARDS)}
    rentals, missing = 0, []
    for f in glob.glob('catalog/page*.json'):
        for e in json.load(open(f)):
            if e.get('tmdb'):
                kind, i = e['tmdb'].split('/')
                shards[kind, int(i) % SHARDS].setdefault(int(i), []).append(rental(e))
                rentals += 1
            else:
                missing.append(unmatched(e))
    before = json.load(open(f'{out}/index.json'))['rentals'] if os.path.exists(f'{out}/index.json') else 0
    if '--force' not in sys.argv and (not rentals or rentals < 0.9 * before):
        sys.exit(f'api: not written: {rentals} rentals with an id, {before} before (--force to write anyway)')
    order = {f: n for n, f in enumerate(FORMAT_ORDER)}
    written = 0
    for (kind, n), ids in shards.items():
        for rs in ids.values():
            rs.sort(key=lambda r: (order.get(r.get('format'), len(order)), r['id']))
        written += write_if_changed(f'{out}/tmdb/{kind}/{n:03}.json', {str(i): ids[i] for i in sorted(ids)})
    missing.sort(key=lambda r: r['id'])
    written += write_if_changed(f'{out}/unmatched.json', missing)
    state = 'catalog-updated.json'
    counts = {kind: sum(len(ids) for (k, _), ids in shards.items() if k == kind) for kind in ('movie', 'tv')}
    written += write_if_changed(f'{out}/index.json', {
        'updated': json.load(open(state))['modified'] if os.path.exists(state) else None,
        'rentals': rentals, 'movie': counts['movie'], 'tv': counts['tv'], 'unmatched': len(missing), 'shards': SHARDS,
        'files': 'tmdb/{movie|tv}/{id % shards, 3 digits}.json', 'unmatched_file': 'unmatched.json',
        'notice': NOTICE})
    print(f'api: {rentals} rentals under {counts["movie"]} films and {counts["tv"]} shows, {len(missing)} without an id; {written} files written')

if __name__ == '__main__':
    main()
