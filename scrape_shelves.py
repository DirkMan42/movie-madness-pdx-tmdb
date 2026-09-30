#!/usr/bin/env python3
"""Reads Movie Madness search cards for catalog entries whose full shelf is
still unknown (shelf_complete: false after build_shelves.py). Resumable, one
request at a time.

Keeps only each card's id and shelf, appended to shelf-cards.jsonl, and every
finished search to shelf-queries.jsonl, so a rerun skips both. Run
build_shelves.py afterwards to merge the cards into the catalog pages.

Order, most entries per request first:
  1. names: each name level seen on a card ("SPIELBERG, STEVEN"), searched as
     "STEVEN SPIELBERG", paging while pages still show that shelf. Names found
     along the way are queued too.
  2. titles on name shelves: one title search per entry still unseen.
  3. titles on mixed shelves (Drama, Foreign > French, ...), the same way.

  --until HH:MM   stop at this local time (next occurrence)
  --window HH:MM-HH:MM
                  run only inside these local hours: exit at once if started
                  outside them (say, after a late wake from sleep), and stop
                  at the end
  --max N         stop after N requests
  --terms REGEX   only entries whose location name matches, e.g.
                  'director|actor|filmmaker|action heroes' (case-insensitive)
"""
import datetime, html, json, os, re, sys, time, urllib.parse, urllib.request
from collections import deque
from build_shelves import parse_cards, term_index, search_query, UA

CARDS, QUERIES, SEARCH = 'shelf-cards.jsonl', 'shelf-queries.jsonl', 'https://www.moviemadness.org/search/'
PAUSE, MAX_OFFSET = 0.4, 996

def arg(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None

def next_time(hhmm, now):
    h, m = map(int, hhmm.split(':'))
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return t if t > now else t + datetime.timedelta(days=1)

def deadline():
    """When to stop, or None. Exits if --window says now is outside it."""
    now = datetime.datetime.now()
    if arg('--window'):
        start, end = arg('--window').split('-')
        # Inside the window when its end comes before its next start.
        if next_time(end, now) > next_time(start, now):
            log(f'outside the {arg("--window")} window; not starting')
            sys.exit(0)
        return next_time(end, now)
    return next_time(arg('--until'), now) if arg('--until') else None

def log(msg):
    print(f'{datetime.datetime.now():%H:%M:%S} {msg}', flush=True)

def load_jsonl(path):
    try:
        return [json.loads(l) for l in open(path) if l.strip()]
    except FileNotFoundError:
        return []

class Stop(Exception):
    pass

def main():
    import glob
    stop_at = deadline()   # first, so it exits before loading anything when outside --window
    entries = {e['id']: e for f in glob.glob('catalog/page*.json') for e in json.load(open(f))}
    terms = {t['id']: t['name'] for t in json.load(open('locations.json'))}
    kinds = {r['id']: r['kind'] for r in json.load(open('shelves.json'))}
    if arg('--terms'):   # leave other locations out entirely: no targets, no names
        rx = re.compile(arg('--terms'), re.I)
        kinds = {t: k for t, k in kinds.items() if rx.search(terms[t])}
        log(f'locations: {", ".join(sorted(terms[t] for t, k in kinds.items() if k in ("named", "mixed")))}')

    cards = {}   # id -> shelf parts, from the cache pages and earlier runs
    for f in glob.glob('cache/*moviemadness.org%2Fsearch*'):
        cards.update(parse_cards(open(f).read()))
    for c in load_jsonl(CARDS):
        cards[c['id']] = c['parts']
    done = {q['key'] for q in load_jsonl(QUERIES)}

    targets = {i for i, e in entries.items() if not e.get('shelf_complete') and kinds_of(e, kinds) and i not in cards}
    log(f'{len(targets)} entries to find; {len(done)} searches already done')

    max_req = int(arg('--max') or 0)
    stats = {'requests': 0, 'errors_in_row': 0}
    cards_out, queries_out = open(CARDS, 'a'), open(QUERIES, 'a')

    def get(params):
        if stop_at and datetime.datetime.now() >= stop_at:
            raise Stop(f'reached {stop_at:%H:%M}')
        if max_req and stats['requests'] >= max_req:
            raise Stop(f'reached {max_req} requests')
        url = SEARCH + '?' + urllib.parse.urlencode(params)
        for attempt in range(3):
            time.sleep(PAUSE if attempt == 0 else 5 * attempt)
            stats['requests'] += 1
            try:
                req = urllib.request.Request(url, headers={'User-Agent': UA})
                page = urllib.request.urlopen(req, timeout=60).read().decode()
                stats['errors_in_row'] = 0
                return page
            except Exception as ex:
                stats['errors_in_row'] += 1
                log(f'  error {ex} on {url}')
                if stats['errors_in_row'] >= 10:
                    raise Stop('10 errors in a row')
        return None

    def names_on(parts, e):
        """Name levels below the entry's term on its card."""
        for t in e.get('location', []):
            if kinds.get(t) in ('named', 'mixed'):
                k = term_index(parts, terms[t])
                if k is not None:
                    return parts[k + 1:]
        return []

    def record(got):
        new = 0
        for i, parts in got.items():
            if i not in cards or cards[i] != parts:
                cards_out.write(json.dumps({'id': i, 'parts': parts}, ensure_ascii=False) + '\n')
            cards[i] = parts
            if i in targets:
                targets.discard(i)
                new += 1
            if i in entries:
                for n in names_on(parts, entries[i]):
                    if n not in queued:
                        queued.add(n)
                        names.append(n)
        cards_out.flush()
        return new

    def search(key, params, keep_paging, max_pages=MAX_OFFSET // 12 + 1):
        """Pages one search while keep_paging(cards) holds. Returns targets found."""
        if key in done:
            return 0
        found = 0
        for offset in range(0, 12 * max_pages, 12):
            page = get({**params, 'offset': offset} if offset else params)
            if page is None:
                return found   # not marked done, so a rerun retries it
            got = parse_cards(page)
            found += record(got)
            if not got or len(got) < 12 or not keep_paging(got):
                break
        queries_out.write(json.dumps({'key': key, 'found': found}) + '\n')
        queries_out.flush()
        done.add(key)
        return found

    # Phase 1 seeds: every name level already on a card.
    names, queued = deque(), set()
    for i, parts in cards.items():
        if i in entries:
            for n in names_on(parts, entries[i]):
                if n not in queued:
                    queued.add(n)
                    names.append(n)

    try:
        log(f'phase 1: names ({len(names)} seeded)')
        n_done = 0
        while names:
            n = names.popleft()
            q = ' '.join(reversed([p.strip() for p in n.split(',', 1)])) if ',' in n else n
            f = search(f'name:{n}', {'query': q, 'search_by': 'All'},
                       lambda got, n=n: any(n in parts for parts in got.values()))
            n_done += 1
            if n_done % 25 == 0:
                log(f'  {n_done} names, {len(names)} queued, {len(targets)} entries left, {stats["requests"]} requests')
        for phase, kind in (('phase 2: titles on name shelves', 'named'), ('phase 3: titles on mixed shelves', 'mixed')):
            todo = sorted((i for i in targets if kinds_of(entries[i], kinds) == kind), key=lambda i: entries[i]['title']['rendered'])
            log(f'{phase} ({len(todo)} entries)')
            for n, i in enumerate(todo, 1):
                if i not in targets:
                    continue
                q = search_query(html.unescape(entries[i]['title']['rendered']))
                search(f'title:{q.casefold()}', {'query': q, 'search_by': 'Title'},
                       lambda got, i=i: i not in got, max_pages=3)   # more pages only while the entry is missing
                if n % 250 == 0:
                    log(f'  {n}/{len(todo)} titles, {len(targets)} entries left, {stats["requests"]} requests')
        log('all phases finished')
    except Stop as why:
        log(f'stopping: {why}')
    log(f'{stats["requests"]} requests this run; {len(targets)} entries still unseen')

def kinds_of(e, kinds):
    ks = [kinds.get(t) for t in e.get('location', [])]
    return 'named' if 'named' in ks else 'mixed' if 'mixed' in ks else None

if __name__ == '__main__':
    main()
