#!/usr/bin/env python3
"""Finds the TMDB id behind each rental's poster and writes it to catalog/ as
`tmdb`: "movie/201085", "tv/13859", or None, with `tmdb_source`: "poster",
"description", "edition", "credits", "language" or "title".

The store's covers are TMDB posters under their TMDB file names (`poster`,
from fetch_media.py or update_catalog.py). TMDB can't look a poster up by
name, so for each distinct poster this searches TMDB for the titles that use
it and takes the result with that exact poster: first among the search
results' own posters; then, since the store's descriptions are TMDB's
overviews, a result whose overview is the rental's description; then in the
top results' full poster lists, since the store's copy may no longer be the
one TMDB shows first.

A poster match is the entry the store linked the title to, exactly; where the
store linked the wrong one, so does this. TMDB has since dropped some posters
the store still shows; those fall back to the single search result with the
same title and year, if there is exactly one (tmdb_source "title").

The store shows the wrong cover on a few percent of rentals, so every id is
checked against the titles TMDB has for it (tmdb-titles.jsonl): an id whose
titles are nothing like the rental's is dropped and kept as `tmdb_rejected`.

Rentals with no usable cover are searched by title and settled by what else is
known: the shelf's director or actor being in the credits (tmdb_source
"credits"), the shelf's language with the year and a fitting title
("language"), or the same title and year ("title"). Those results are kept in
tmdb-by-title.jsonl.

A rental still without an id takes the one its other editions have: rentals
with the same title and year, when they agree (tmdb_source "edition").

Results are kept in tmdb-posters.jsonl, one line per poster, so a rerun only
looks up new posters. The TMDB token (API Read Access Token) is read from
~/.config/mmboxmonkey/tmdb-token.

  --max N    stop after N TMDB requests
  --retry    look up posters again that found nothing before
"""
import difflib, fcntl, glob, html, json, os, re, sys, threading, time, urllib.error, urllib.parse, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from build_shelves import search_query
from scrape_shelves import arg, load_jsonl, log
from update_catalog import write_json

TOKEN_FILE = os.path.expanduser('~/.config/mmboxmonkey/tmdb-token')
RESULTS, TITLES, BY_TITLE = 'tmdb-posters.jsonl', 'tmdb-titles.jsonl', 'tmdb-by-title.jsonl'
API = 'https://api.themoviedb.org/3/'
PAUSE, LISTS = 0.05, 6   # seconds between a worker's requests; poster lists to open per poster
WORKERS = 6              # about 25 requests a second in all; TMDB allows around 50 per IP

# Foreign shelves by country -> TMDB original-language codes.
LANGUAGES = {
    'French': 'fr', 'Japanese': 'ja', 'Japanese Horror': 'ja', 'Samurai Films': 'ja', 'Chinese / Hong Kong': 'zh cn',
    'Italian': 'it', 'German': 'de', 'Spanish': 'es ca eu gl', 'Latin American': 'es pt', 'Korean': 'ko',
    'Russian': 'ru', 'Swedish': 'sv', 'Danish': 'da', 'Polish': 'pl', 'Czech': 'cs sk', 'Czech Animation': 'cs sk',
    'Indian': 'hi ta te bn ml kn mr pa', 'Iranian': 'fa', 'Dutch': 'nl', 'Finnish': 'fi', 'Hungarian': 'hu',
    'Norwegian': 'no nb', 'Greek': 'el', 'Turkish': 'tr', 'Thai': 'th', 'Brazilian': 'pt', 'Portuguese': 'pt',
    'Israeli': 'he', 'Vietnamese': 'vi', 'Yugoslavian': 'sr hr sh sl mk bs', 'Romanian': 'ro', 'Icelandic': 'is',
    'Filipino': 'tl', 'Indonesian': 'id', 'Belgian': 'fr nl', 'Swiss': 'fr de it',
}

class Stop(Exception):
    pass

def queries(title):
    """Searches to try for one catalog title, most specific first."""
    q = search_query(html.unescape(title))
    first = q.split('/')[0].strip()   # double features: the first film
    series = re.sub(r'\s+[–-]?\s*(Vol\.?|Volume|Season|Series|Set|Collection|Complete|Disc)\b.*', '', first, flags=re.I).strip(' –-')
    return [v for v in dict.fromkeys([q, first, series, re.sub(r'\s+\d{4}$', '', series)]) if v]

def plain(title):
    """A title for comparing: letters and digits only, "&" as "and"."""
    return re.sub(r'[^a-z0-9]+', '', title.casefold().replace('&', 'and'))

def tmdb_titles(api, tmdb):
    """Every title TMDB lists for an entry: its own, the original, alternatives and translations."""
    d = api(tmdb, append_to_response='alternative_titles,translations')
    alt = d.get('alternative_titles', {})
    found = [d.get('title'), d.get('name'), d.get('original_title'), d.get('original_name')]
    found += [t.get('title') for t in alt.get('titles', []) + alt.get('results', [])]
    found += [t.get('data', {}).get(k) for t in d.get('translations', {}).get('translations', []) for k in ('title', 'name')]
    return list(dict.fromkeys(t for t in found if t))

ARTICLE = re.compile(r'^(the|a|an|le|la|les|l|el|los|las|il|lo|i|gli|der|die|das|un|une|una|uno)\s+', re.I)
NUMBERS = {w: str(n) for n, ws in enumerate((
    'one i', 'two ii', 'three iii', 'four iv', 'five v', 'six vi', 'seven vii', 'eight viii', 'nine ix', 'ten x',
    'eleven xi', 'twelve xii', 'thirteen xiii', 'fourteen xiv', 'fifteen xv'), 1) for w in ws.split()}

def loose(title):
    """A title for checking a link: no leading article, and numbers as digits however
    written ("Part II", "Part Two", "Part 2"; "04" as "4")."""
    t = ARTICLE.sub('', title.strip().casefold())
    t = re.sub(r'[a-z]+|\d+', lambda m: NUMBERS.get(m.group(), m.group().lstrip('0') or '0'), t)
    return plain(t)

def title_fits(title, tmdb_titles):
    """Whether a catalog title is plausibly one of a TMDB entry's titles. The store
    shows the wrong cover on a few percent of rentals, and a poster match then
    finds the wrong film; those have titles nothing alike."""
    t = html.unescape(title)
    parts = [t] + re.split(r'\s*/\s*', re.sub(r'\([^)]*\)', '', t))   # each half of a double feature
    ours = {loose(q) for part in parts for q in queries(part)} - {''}
    theirs = {loose(x) for x in tmdb_titles} - {''}
    if ours & theirs:
        return True
    for a in ours:
        for b in theirs:
            if min(len(a), len(b)) >= 6 and (a in b or b in a):
                return True
            if (abs(len(a) - len(b)) <= 0.3 * max(len(a), len(b)) and re.findall(r'\d+', a) == re.findall(r'\d+', b)
                    and difflib.SequenceMatcher(None, a, b).ratio() >= 0.85):
                return True
    return False

def shelf_person(e):
    """The director or actor a rental is shelved under ("first last"), from "LAST, FIRST (WRITTEN BY)"."""
    level = (e.get('shelf') or '').rsplit(' > ', 1)[-1] if ' > ' in (e.get('shelf') or '') else ''
    if ',' not in level or level.upper() != level:
        return None
    last, first = re.sub(r'\(.*', '', level).split(',', 1)
    return plain(first + last) or None

def shelf_languages(e):
    """TMDB language codes for a rental on a foreign country's shelf; none for English-speaking ones."""
    parts = (e.get('shelf') or '').split(' > ')
    return set(LANGUAGES.get(parts[1], '').split()) if len(parts) > 1 and parts[0] == 'Foreign' else set()

def lookup_key(e):
    """What one title search serves: the title and year, and the shelf's person and languages."""
    title, year = edition_key(e) if e.get('year') else (edition_key({**e, 'year': []})[0], ())
    return '|'.join([title, ','.join(year), shelf_person(e) or '', ','.join(sorted(shelf_languages(e)))])

def edition_key(e):
    """What editions of one film share: its title without the parentheses, and its year."""
    return plain(re.sub(r'\([^)]*\)', '', html.unescape(e['title']['rendered']))), tuple(e['year'])

def words(description):
    """A description for comparing; '' when too short to identify anything."""
    w = re.sub(r'[^a-z0-9]+', ' ', (description or '').casefold()).strip()
    return w if len(w) >= 40 else ''

def same_text(overview, texts):
    """Whether a TMDB overview is one of the store's descriptions, give or take small edits."""
    o = words(overview)
    return bool(o) and any(o == t or abs(len(o) - len(t)) < 0.2 * len(t)
                           and difflib.SequenceMatcher(None, t, o).ratio() >= 0.9 for t in texts)

def source(how):
    return {'title and year': 'title', 'description': 'description', 'credits': 'credits',
            'language': 'language'}.get(how, 'poster')

def main():
    if not os.path.exists(TOKEN_FILE):
        log(f'no TMDB token at {TOKEN_FILE}; skipping')
        return
    token = open(TOKEN_FILE).read().strip()
    lock = open(RESULTS, 'a')   # held until exit, so a second run (the daily update) skips
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log('another resolve_tmdb.py is running; skipping')
        return
    max_req, stats = int(arg('--max') or 0), {'requests': 0}
    counting = threading.Lock()

    def api(path, **params):
        if max_req and stats['requests'] >= max_req:
            raise Stop(f'reached {max_req} requests')
        url = API + path + ('?' + urllib.parse.urlencode(params) if params else '')
        for attempt in range(4):
            time.sleep(PAUSE if attempt == 0 else 5 * attempt)
            with counting:
                stats['requests'] += 1
            try:
                req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
                return json.load(urllib.request.urlopen(req, timeout=30))
            except urllib.error.HTTPError as ex:
                if ex.code == 404:
                    return {}
                if ex.code == 401:
                    raise Stop('TMDB rejected the token')
                log(f'  error {ex.code} on {path}')
            except Exception as ex:
                log(f'  error {ex} on {path}')
        raise Stop(f'giving up on {path}')

    def resolve(poster, entries):
        """(tmdb, how) for one poster, from the titles of the rentals that use it."""
        want, candidates = '/' + poster, {}
        texts = {words(descriptions.get(e['id'])) for e in entries} - {''}
        years = {y for e in entries for y in e.get('year') or []}
        tried = set()
        for e in entries[:3]:
            for q in queries(e['title']['rendered']):
                if q.casefold() in tried:
                    continue
                tried.add(q.casefold())
                results = [r for r in api('search/multi', query=q, include_adult='true').get('results', [])
                           if r.get('media_type') in ('movie', 'tv')]
                for r in results:
                    if r.get('poster_path') == want:
                        return f'{r["media_type"]}/{r["id"]}', 'search'
                for r in results:   # the store's descriptions are TMDB's overviews, and search results carry them
                    if same_text(r.get('overview'), texts):
                        return f'{r["media_type"]}/{r["id"]}', 'description'
                for r in results:
                    key = f'{r["media_type"]}/{r["id"]}'
                    candidates.setdefault(key, ((r.get('release_date') or r.get('first_air_date') or '')[:4],
                                                {plain(r.get(k) or '') for k in ('title', 'name', 'original_title', 'original_name')}))
        by_year = sorted(candidates, key=lambda k: candidates[k][0] not in years)   # stable: TMDB's order within each
        for key in by_year[:LISTS]:
            if any(p.get('file_path') == want for p in api(key + '/images').get('posters', [])):
                return key, 'poster list'
        # TMDB has dropped some posters the store still shows. Then take the one
        # result with the same title and year, if there is exactly one.
        same = [k for k, (year, titles) in candidates.items() if year in years and titles & {plain(q) for q in tried}]
        return (same[0], 'title and year') if len(same) == 1 else (None, None)

    def by_title(e):
        """(tmdb, how) for a rental with no usable cover, from a title search and what
        else is known about it. Each rule was checked against rentals with poster ids
        and disagreed with under 2% of them:
          credits   the one result with the shelf's director or actor in its credits
          language  the one result in the shelf's language, within a year, whose title fits
          title and year  the one result with the same title, within a year"""
        found, years = {}, [int(y) for y in e.get('year') or [] if y.isdigit()]
        for q in queries(e['title']['rendered']):
            for r in api('search/multi', query=q, include_adult='true').get('results', []):
                if r.get('media_type') in ('movie', 'tv'):
                    found.setdefault(f'{r["media_type"]}/{r["id"]}', (q, r))
        def near(r):
            y = (r.get('release_date') or r.get('first_air_date') or '')[:4]
            return y.isdigit() and any(abs(int(y) - x) <= 1 for x in years)
        def names(r):
            return [r[k] for k in ('title', 'name', 'original_title', 'original_name') if r.get(k)]
        who = shelf_person(e)
        if who:
            hits = []
            for key in sorted(found, key=lambda k: not near(found[k][1]))[:5]:
                credits = api(key + ('/credits' if key.startswith('movie') else '/aggregate_credits'))
                if who in {plain(p.get('name') or '') for p in credits.get('cast', []) + credits.get('crew', [])}:
                    hits.append(key)
            if len(hits) == 1:
                return hits[0], 'credits'
        langs = shelf_languages(e)
        if langs:
            hits = [k for k, (q, r) in found.items() if r.get('original_language') in langs and near(r)
                    and title_fits(e['title']['rendered'], names(r))]
            if len(hits) == 1:
                return hits[0], 'language'
        hits = [k for k, (q, r) in found.items() if near(r) and loose(q) in {loose(x) for x in names(r)}]
        return (hits[0], 'title and year') if len(hits) == 1 else (None, None)

    def catalog():
        return {f: json.load(open(f)) for f in glob.glob('catalog/page*.json')}

    descriptions = {r['id']: r['description'] for f in glob.glob('catalog-media/page*.json') for r in json.load(open(f))}
    descriptions.update((r['id'], r['description']) for r in load_jsonl('catalog-media/updates.jsonl'))

    by_poster = defaultdict(list)
    for es in catalog().values():
        for e in es:
            if e.get('poster'):
                by_poster[e['poster']].append(e)
    known, sources = {}, {}
    for r in load_jsonl(RESULTS):   # a later line for the same poster replaces an earlier one
        known[r['poster']], sources[r['poster']] = r['tmdb'], source(r['how'])
    todo = [p for p in by_poster if p not in known or '--retry' in sys.argv and known[p] is None]
    log(f'{len(by_poster)} distinct posters; {len(todo)} to look up')

    # WORKERS posters at a time; results are written here, in the order they finish.
    found, pool = 0, ThreadPoolExecutor(WORKERS)
    lookups = {pool.submit(resolve, p, by_poster[p]): p for p in todo}
    try:
        with open(RESULTS, 'a') as out:
            for n, done in enumerate(as_completed(lookups), 1):
                poster, (tmdb, how) = lookups[done], done.result()
                known[poster], sources[poster] = tmdb, source(how)
                found += bool(tmdb)
                out.write(json.dumps({'poster': poster, 'tmdb': tmdb, 'how': how}) + '\n')
                out.flush()
                if n % 1000 == 0:
                    log(f'  {n}/{len(todo)} posters, {found} matched, {stats["requests"]} requests')
        log('all posters looked up')
    except Stop as why:
        log(f'stopping: {why}')
    pool.shutdown(cancel_futures=True)

    # Every title TMDB has for each id found, to check the store's links against.
    titles = {r['tmdb']: r['titles'] for r in load_jsonl(TITLES)}
    need = sorted({t for t in known.values() if t} - set(titles))
    if need:
        log(f'{len(need)} TMDB entries to fetch titles for')
        pool = ThreadPoolExecutor(WORKERS)
        fetches = {pool.submit(tmdb_titles, api, t): t for t in need}
        try:
            with open(TITLES, 'a') as out:
                for n, done in enumerate(as_completed(fetches), 1):
                    titles[fetches[done]] = done.result()
                    out.write(json.dumps({'tmdb': fetches[done], 'titles': done.result()}, ensure_ascii=False) + '\n')
                    if n % 5000 == 0:
                        log(f'  {n}/{len(need)} entries, {stats["requests"]} requests')
        except Stop as why:
            log(f'stopping: {why}')
        pool.shutdown(cancel_futures=True)
    log(f'{found} matched by poster this run; {stats["requests"]} requests')

    def assign(pages):
        """Sets tmdb on every rental from its poster, then from its other editions."""
        rejected = copied = 0
        editions = defaultdict(set)   # (title, year) -> ids its rentals have
        for es in pages.values():
            for e in es:
                e['tmdb'] = known.get(e.get('poster'))
                e['tmdb_rejected'] = None
                if e['tmdb'] in titles and not title_fits(e['title']['rendered'], titles[e['tmdb']]):
                    e['tmdb'], e['tmdb_rejected'] = None, e['tmdb']   # the store's cover is another film's
                    rejected += 1
                e['tmdb_source'] = sources[e['poster']] if e['tmdb'] else None
                if e['tmdb'] and e.get('year'):
                    editions[edition_key(e)].add(e['tmdb'])
        # A rental with no id of its own takes the id of another edition: one with the
        # same title and year, when all of those that have an id agree on it.
        for es in pages.values():
            for e in es:
                if not e['tmdb'] and e.get('year') and len(editions.get(edition_key(e), ())) == 1:
                    (e['tmdb'],), e['tmdb_source'] = editions[edition_key(e)], 'edition'
                    copied += 1
        return rejected, copied

    # Rentals still without an id (no cover, or the wrong one) are searched by title.
    pages = catalog()
    assign(pages)
    groups = {}
    for es in pages.values():
        for e in es:
            if not e['tmdb'] and (e.get('year') or shelf_person(e)):
                groups.setdefault(lookup_key(e), e)
    titled = {r['key']: (r['tmdb'], r['how']) for r in load_jsonl(BY_TITLE)}
    todo = [k for k in groups if k not in titled or '--retry' in sys.argv and titled[k][0] is None]
    log(f'{len(groups)} titles without an id; {len(todo)} to search for')
    found, pool = 0, ThreadPoolExecutor(WORKERS)
    searches = {pool.submit(by_title, groups[k]): k for k in todo}
    try:
        with open(BY_TITLE, 'a') as out:
            for n, done in enumerate(as_completed(searches), 1):
                key, (tmdb, how) = searches[done], done.result()
                titled[key] = tmdb, how
                found += bool(tmdb)
                out.write(json.dumps({'key': key, 'tmdb': tmdb, 'how': how}) + '\n')
                out.flush()
                if n % 2000 == 0:
                    log(f'  {n}/{len(todo)} titles, {found} matched, {stats["requests"]} requests')
        log('all titles searched')
    except Stop as why:
        log(f'stopping: {why}')
    pool.shutdown(cancel_futures=True)
    log(f'{found} matched by title this run; {stats["requests"]} requests in all')

    # Read the catalog again before writing: a long run may overlap the daily update.
    pages = catalog()
    rejected, copied = assign(pages)
    have = by_search = 0
    for f, es in pages.items():
        for e in es:
            tmdb, how = titled.get(lookup_key(e), (None, None)) if not e['tmdb'] else (None, None)
            if tmdb and tmdb != e['tmdb_rejected']:
                e['tmdb'], e['tmdb_source'] = tmdb, source(how)
                by_search += 1
            have += bool(e['tmdb'])
        write_json(f, es)
    log(f'tmdb written to the catalog: {have} rentals have one ({copied} from another edition, {by_search} by title search); '
        f'{rejected} dropped because the title is not one of the TMDB entry\'s')

if __name__ == '__main__':
    main()
