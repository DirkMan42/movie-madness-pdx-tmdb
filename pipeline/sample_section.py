#!/usr/bin/env python3
"""Tests whether a mixed section's uncarded titles are on its plain shelf, as
done for Drama before adding it to build_shelves.INFERRED_PLAIN.

  python3 ../pipeline/sample_section.py 'Comedy'

1. Searches, in full, every name shelf seen under the section that hasn't
   been searched yet (as scrape_shelves.py phase 1 would).
2. Samples 100 random titles in the section that have no card yet, one
   title search each.
3. Any new name shelf a sample turns up is searched in full, then it samples
   again. It stops after two samples in a row find no new names (or --rounds).

Cards and finished searches go to the scraper's own files, so a later
scrape skips them. It doesn't change the catalog; run build_shelves.py after.
"""
import datetime, glob, html, json, random, sys, time, urllib.parse, urllib.request
from collections import Counter
from build_shelves import parse_cards, split_temporary, term_index, search_query, UA

SAMPLE, PAUSE = 100, 0.4
section = sys.argv[1]
rounds = int(sys.argv[sys.argv.index('--rounds') + 1]) if '--rounds' in sys.argv else 5

entries = {e['id']: e for f in glob.glob('catalog/page*.json') for e in json.load(open(f))}
term = next(t for t in json.load(open('locations.json')) if t['name'].rstrip('*') == section.rstrip('*'))
cards = {}
for f in glob.glob('cache/*moviemadness.org%2Fsearch*'):
    cards.update(parse_cards(open(f).read()))
for l in open('shelf-cards.jsonl'):
    c = json.loads(l)
    cards[c['id']] = c['parts']
searched = {json.loads(l)['key'][5:] for l in open('shelf-queries.jsonl') if json.loads(l)['key'].startswith('name:')}
cards_out, queries_out = open('shelf-cards.jsonl', 'a'), open('shelf-queries.jsonl', 'a')
requests = 0

def log(msg):
    print(f'{datetime.datetime.now():%H:%M:%S} {msg}', flush=True)

def get(params):
    global requests
    url = 'https://www.moviemadness.org/search/?' + urllib.parse.urlencode(params)
    for attempt in range(3):
        time.sleep(PAUSE if attempt == 0 else 5 * attempt)
        requests += 1
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=60).read().decode()
        except Exception as ex:
            log(f'  error {ex}')
    return ''

def record(got):
    for i, p in got.items():
        if cards.get(i) != p:
            cards_out.write(json.dumps({'id': i, 'parts': p}, ensure_ascii=False) + '\n')
        cards[i] = p
    cards_out.flush()

def level(i):
    """The name under the section on this title's card: '' if plain, None if no card shows the section."""
    if i not in cards:
        return None
    _, q = split_temporary(cards[i])
    k = term_index(q, term['name'])
    return None if k is None else (q[k + 1] if len(q) > k + 1 else '')

def ours(i):
    return term['id'] in entries[i].get('location', [])

def names_seen():
    return {level(i) for i in cards if i in entries and ours(i) and level(i)}

def search_name(name):
    q = ' '.join(reversed([p.strip() for p in name.split(',', 1)])) if ',' in name else name
    for offset in range(0, 996, 12):
        got = parse_cards(get({'query': q, 'search_by': 'All', **({'offset': offset} if offset else {})}))
        record(got)
        if len(got) < 12 or not any(name in p for p in got.values()):
            break
    queries_out.write(json.dumps({'key': f'name:{name}', 'found': 0}) + '\n')
    queries_out.flush()
    searched.add(name)
    log(f'searched {name}: {sum(1 for i in entries if ours(i) and level(i) == name)} {section} titles on it')

for n in sorted(names_seen() - searched):
    search_name(n)

clean = 0
for r in range(1, rounds + 1):
    pool = sorted(i for i in entries if ours(i) and level(i) is None)
    if not pool:
        break
    sample = random.Random(f'{section}-{r}').sample(pool, min(SAMPLE, len(pool)))
    log(f'sample {r}: {len(sample)} of {len(pool)} uncarded {section} titles')
    for i in sample:
        q = search_query(html.unescape(entries[i]['title']['rendered']))
        for offset in (0, 12, 24):
            got = parse_cards(get({'query': q, 'search_by': 'Title', **({'offset': offset} if offset else {})}))
            record(got)
            if i in got or len(got) < 12:
                break
        queries_out.write(json.dumps({'key': f'title:{q.casefold()}', 'found': int(i in cards)}) + '\n')
    queries_out.flush()
    res = Counter('plain' if level(i) == '' else 'no card or a label' if level(i) is None else 'name' for i in sample)
    new = sorted(names_seen() - searched)
    log(f'  result: {dict(res)}; new names: {new or "none"}')
    for n in new:
        search_name(n)
    clean = 0 if new else clean + 1
    if clean == 2:
        break

log(f'{section}: {"two clean samples in a row" if clean == 2 else "stopped without two clean samples"}; '
    f'name shelves: {dict(Counter(level(i) for i in entries if ours(i) and level(i)))}; {requests} requests')
