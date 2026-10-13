#!/usr/bin/env python3
"""Builds a location-term -> shelf table from Movie Madness search cards and
adds each catalog entry's shelf to catalog/page*.json.

The API's location term is a single flat name. The search cards show the full
shelf, which is one of:
  bare      "Sci-fi"                                  (term is the whole shelf)
  sub-shelf "Leviathans & Behemoths > Shark!"         (term is the last level)
  named     "Hollywood Directors > SPIELBERG, STEVEN" (name level below the term)
  mixed     "Drama", but "Drama > SARANDON, SUSAN" for a few titles
            (a location stays plain when its only name shelves are a minority
            that scrape_shelves.py has searched in full)

Temporary shelves are displays titles rotate through: Curated, Staff Picks,
VHS Spotlight, and every New Release and New Arrival. A card may show one in
place of the permanent shelf ("Staff Picks") or above it ("DVD New Release >
TV Heritage"), and some API locations are one ("New Release (Foreign)"). They
are kept apart from the permanent shelf.

Cards come from cache/ (the harness's page cache) and shelf-cards.jsonl (from
scrape_shelves.py). Terms with no card are probed with one title search each
(--probe), saved into the cache.

Adds to each entry:
  shelf           best known shelf text, or null
  shelf_complete  true when shelf is the full card text
  shelf_source    "card" (the entry's own card), "term" (from the table),
                  "inferred" (a mixed location sampled as plain, see INFERRED_PLAIN), or null
  temporary_shelf the temporary shelf it's on now, or null
"""
import glob, html, json, re, sys, time, urllib.parse, urllib.request
from collections import Counter, defaultdict

CACHE = 'cache/'
UA = 'Mozilla/5.0 (X11; Linux x86_64) mmboxmonkey-test'

def cache_path(url):
    # Same file name as harness.js cachedFetch: encodeURIComponent(url).slice(0, 200)
    return CACHE + urllib.parse.quote(url, safe="-_.!~*'()")[:200]

def fetch(url):
    try:
        return open(cache_path(url)).read()
    except FileNotFoundError:
        pass
    time.sleep(0.4)
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    text = urllib.request.urlopen(req, timeout=60).read().decode()
    open(cache_path(url), 'w').write(text)
    return text

def parse_cards(page):
    out = {}
    for m in re.finditer(r'data-wp-id="(\d+)"(.*?)(?=data-wp-id="|\Z)', page, re.S):
        s = re.search(r'fill-yellow.*?</svg>\s*<span[^>]*>(.*?)</span>', m.group(2), re.S)
        if s:
            parts = [html.unescape(re.sub(r'\s+', ' ', p)).strip()
                     for p in re.split(r'<svg.*?</svg>', s.group(1), flags=re.S)]
            out[int(m.group(1))] = [p for p in parts if p]
    return out

norm = lambda s: re.sub('[‘’]', "'", s.rstrip('*')).strip().casefold()

def term_index(parts, term):
    """Position of the term in the card's shelf, or None when the card shows a
    display label (Staff Picks, Curated...) instead of the real shelf."""
    n = norm(term)
    for i, p in enumerate(parts):
        if norm(p) == n:
            return i
    return None

TEMPORARY = re.compile(r'^(curated|staff picks|vhs spotlight|new arrival\b.*|(.+ )?new release\b.*)$', re.I)

def is_temporary(name):
    return bool(TEMPORARY.match(norm(name)))

def split_temporary(parts):
    """Card shelf -> (leading temporary levels, the permanent rest)."""
    k = 0
    while k < len(parts) and is_temporary(parts[k]):
        k += 1
    return parts[:k], parts[k:]

# Mixed locations whose uncarded titles are taken to be on the plain section:
# every name shelf sampling turned up has been searched in full, and further
# samples found no others.
INFERRED_PLAIN = {
    'Drama*': '3 samples of 100 titles on 2026-09-30; after searching Sarandon, '
              'Wahlberg and Witherspoon, 197 carded titles all plain',
    'Comedy': '2 samples of 100 titles on 2026-09-30 (sample_section.py); after searching '
              'Sarandon, Wahlberg, Witherspoon and Tomlin, 200 carded titles all plain',
}

def search_query(title):
    t = re.sub(r'\([^)]*\)', '', title).strip()
    # "Night Agent, The: Season One" -> "The Night Agent: Season One"
    m = re.match(r'(.*?), (The|A|An)($|[:/…–].*|\s[–/].*)', t)
    if m:
        t = f'{m.group(2)} {m.group(1)}{m.group(3)}'
    t = re.sub(r'[\'"“”!?]', '', t.replace(':', ' '))
    return re.sub(r'\s+', ' ', t).strip()

def main():
    probe = '--probe' in sys.argv
    pages = sorted(glob.glob('catalog/page*.json'), key=lambda f: int(re.sub(r'\D', '', f)))
    catalog = {f: json.load(open(f)) for f in pages}
    entries = {e['id']: e for es in catalog.values() for e in es}
    terms = {t['id']: t for t in json.load(open('locations.json'))}
    by_term = defaultdict(list)
    for e in entries.values():
        for t in e.get('location', []):
            by_term[t].append(e)

    cards = {}
    for f in glob.glob(CACHE + '*moviemadness.org%2Fsearch*'):
        cards.update(parse_cards(open(f).read()))
    try:   # cards saved by scrape_shelves.py
        for line in open('shelf-cards.jsonl'):
            c = json.loads(line)
            cards[c['id']] = c['parts']
    except FileNotFoundError:
        pass

    def shows(i, t):
        return t in terms and term_index(cards[i], terms[t]['name']) is not None

    def seen_terms():
        return {t for i in cards if i in entries for t in entries[i].get('location', []) if shows(i, t)}

    # Step 2: one title search for each term with no cached card.
    probes = {}
    if probe:
        missing = [t for t in terms if by_term[t] and t not in seen_terms()]
        print(f'probing {len(missing)} terms', file=sys.stderr)
        for n, t in enumerate(missing, 1):
            found = None
            for e in sorted(by_term[t], key=lambda e: len(e['title']['rendered']))[:3]:
                q = search_query(html.unescape(e['title']['rendered']))
                url = f'https://www.moviemadness.org/search/?query={urllib.parse.quote(q, safe="-_.!~*()")}'
                try:
                    got = parse_cards(fetch(url))
                except Exception as ex:
                    print(f'  {terms[t]["name"]}: {ex}', file=sys.stderr)
                    continue
                cards.update(got)
                if e['id'] in got and shows(e['id'], t):
                    found = e['id']
                    break
            probes[t] = found
            print(f'  [{n}/{len(missing)}] {terms[t]["name"]}: '
                  f'{" > ".join(cards[found]) if found else "not found"}', file=sys.stderr)

    # Step 1: vote on each term's shelf from every card that shows it.
    votes = defaultdict(Counter)   # term -> prefix -> cards
    named = defaultdict(Counter)   # term -> prefix -> cards with a level below the term
    unsearched = Counter()         # term -> of those, cards whose name hasn't been searched in full
    try:   # names scrape_shelves.py has searched in full
        searched = {json.loads(l)['key'][5:] for l in open('shelf-queries.jsonl')
                    if json.loads(l)['key'].startswith('name:')}
    except FileNotFoundError:
        searched = set()
    labels = Counter()             # other labels shown instead of the shelf
    temporary = Counter()          # temporary shelves on cards
    for i, parts in cards.items():
        e = entries.get(i)
        if not e:
            continue
        temp, parts = split_temporary(parts)
        if temp:
            temporary[' > '.join(temp)] += 1
        for t in e.get('location', []):
            if t in terms and is_temporary(terms[t]['name']):
                continue
            k = term_index(parts, terms[t]['name']) if t in terms else None
            if k is None:
                if len(e['location']) == 1 and parts:
                    labels[' > '.join(parts)] += 1
                continue
            prefix = ' > '.join(parts[:k + 1])
            votes[t][prefix] += 1
            if len(parts) > k + 1:
                named[t][prefix] += 1
                if parts[k + 1] not in searched:
                    unsearched[t] += 1

    table = []
    for t, info in sorted(terms.items(), key=lambda x: x[1]['name'].casefold()):
        row = {'id': t, 'name': info['name'], 'entries': len(by_term[t])}
        if is_temporary(info['name']):
            row.update(shelf=None, kind='temporary')
        elif votes[t]:
            prefix, n = votes[t].most_common(1)[0]
            n_cards, n_named = sum(votes[t].values()), sum(named[t].values())
            # named: most titles sit under a name; mixed: only some do, so the
            # table can't say which of the others have one either. A minority
            # name shelf that's been searched in full has all its titles
            # carded already, so it leaves the rest of the section plain.
            kind = ('named' if n_named * 2 >= n_cards else 'mixed' if unsearched[t]
                    else 'bare' if ' > ' not in prefix else 'sub-shelf')
            row.update(shelf=prefix, kind=kind, cards=n_cards, named_cards=n_named)
            if n_named and kind != 'named':
                row['unsearched_named_cards'] = unsearched[t]
            others = {p: c for p, c in votes[t].items() if p != prefix}
            if others:
                row['other_shelves'] = others
        else:
            row.update(shelf=None, kind='unknown')
        table.append(row)
    json.dump(table, open('shelves.json', 'w'), indent=1, ensure_ascii=False)
    rows = {r['id']: r for r in table}
    sections = {r['shelf'].split(' > ')[0] for r in table if r['shelf']}

    # Merge into the catalog pages.
    src, src_temp = Counter(), Counter()
    for f, es in catalog.items():
        for e in es:
            locs = e.get('location', [])
            temp_locs = [t for t in locs if t in terms and is_temporary(terms[t]['name'])]
            locs = [t for t in locs if t not in temp_locs]
            shelf, complete, source = None, False, None
            temp, parts = split_temporary(cards.get(e['id']) or [])
            if temp:
                temp_shelf = ' > '.join(temp)
            elif temp_locs:
                temp_shelf = html.unescape(terms[temp_locs[0]]['name']).rstrip('*')
            else:
                temp_shelf = None
            usable = [t for t in locs if rows.get(t) and rows[t]['shelf']]
            if parts and (not usable and parts[0] in sections   # no location to check the card against
                          or any(term_index(parts, terms[t]['name']) is not None for t in locs if t in terms)):
                shelf, complete, source = ' > '.join(parts), True, 'card'
            else:
                for t in locs:
                    r = rows.get(t)
                    if r and r['shelf']:
                        shelf, complete, source = r['shelf'], r['kind'] in ('bare', 'sub-shelf'), 'term'
                        if r['name'] in INFERRED_PLAIN and r['kind'] != 'named':
                            complete, source = True, 'inferred'
                        break
            e.update(shelf=shelf, shelf_complete=complete, shelf_source=source, temporary_shelf=temp_shelf)
            src[(source, complete)] += 1
            if temp_shelf:
                src_temp[(shelf is not None, complete)] += 1
        json.dump(es, open(f, 'w'))

    kinds = Counter()
    for r in table:
        kinds[r['kind']] += r['entries']
    print(f'terms: {len(table)}; entries by term kind: {dict(kinds)}')
    if probe:
        print(f'probed {len(probes)} terms, found a card for {sum(v is not None for v in probes.values())}')
    print(f'temporary shelves on cards: {dict(temporary)}')
    print(f'other labels ignored: {dict(labels)}')
    print(f'entries on a temporary shelf: {sum(src_temp.values())} '
          f'(permanent shelf known: {src_temp[(True, True)]} complete, {src_temp[(True, False)]} section only; '
          f'unknown: {src_temp[(False, False)]})')
    print('entries:')
    for (s, c), n in sorted(src.items(), key=lambda x: -x[1]):
        print(f'  {n:6}  source={s} complete={c}')

if __name__ == '__main__':
    main()
