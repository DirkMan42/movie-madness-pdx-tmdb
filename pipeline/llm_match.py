#!/usr/bin/env python3
"""Pilot: has a model pick TMDB ids for rentals the rules left without one.

  llm_match.py candidates [--sample N] [--seed S]
      Picks N rentals at random from those without an id (200, seed 1) and
      searches TMDB for each, keeping up to 8 films or shows per rental in
      llm-candidates.jsonl. Only searches for rentals not already there.

  llm_match.py pick [--model M] [--batch B]
      Sends the rentals in llm-candidates.jsonl to the model, B at a time (50),
      with their candidates, and keeps its answers in llm-picks.jsonl: a TMDB id
      from the candidates or none, and how sure it is. Needs the anthropic
      package and an API key (ANTHROPIC_API_KEY or an `ant auth login` profile).

Nothing here changes the catalog: the picks are for review, and the ones that
hold up go into overrides.csv.
"""
import glob, html, json, random, sys, time, urllib.error, urllib.parse, urllib.request
from resolve_tmdb import TOKEN_FILE, API, queries, rental_years, whole
from scrape_shelves import arg, load_jsonl, log

CANDIDATES, PICKS = 'llm-candidates.jsonl', 'llm-picks.jsonl'
KEEP = 8

def tmdb(token, path, **params):
    url = API + path + '?' + urllib.parse.urlencode(params)
    for attempt in range(4):
        time.sleep(0.1 if attempt == 0 else 5 * attempt)
        try:
            req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
            return json.load(urllib.request.urlopen(req, timeout=30))
        except urllib.error.HTTPError as ex:
            if ex.code in (401, 404):
                raise
            log(f'  error {ex.code} on {path}')
        except Exception as ex:
            log(f'  error {ex} on {path}')
    sys.exit(f'giving up on {url}')

def candidate(r):
    """What the model sees of one TMDB search result."""
    kind = r['media_type']
    date = r.get('release_date') or r.get('first_air_date') or ''
    return {'tmdb': f"{kind}/{r['id']}", 'title': r.get('title') or r.get('name'),
            'original': r.get('original_title') or r.get('original_name'), 'year': date[:4] or None,
            'language': r.get('original_language'), 'overview': (r.get('overview') or '')[:240]}

def rentals():
    """Every rental without an id, with its description."""
    desc = {r['id']: r['description'] for f in glob.glob('catalog-media/page*.json') for r in json.load(open(f))}
    desc.update((r['id'], r['description']) for r in load_jsonl('catalog-media/updates.jsonl'))
    out = []
    for f in sorted(glob.glob('catalog/page*.json')):
        for e in json.load(open(f)):
            if not e.get('tmdb'):
                out.append((e, (desc.get(e['id']) or '')[:400]))
    return out

def find_candidates():
    token = open(TOKEN_FILE).read().strip()
    n, seed = int(arg('--sample') or 200), int(arg('--seed') or 1)
    pool = rentals()
    sample = random.Random(seed).sample(pool, n)
    done = {r['id'] for r in load_jsonl(CANDIDATES)}
    log(f'{len(pool)} rentals without an id; {n} sampled, {len(done)} already searched')
    with open(CANDIDATES, 'a') as out:
        for e, description in sample:
            if e['id'] in done:
                continue
            found = {}
            years = rental_years(e)
            for q in queries(e['title']['rendered']):
                for r in tmdb(token, 'search/multi', query=q, include_adult='true').get('results', []):
                    if r.get('media_type') in ('movie', 'tv'):
                        found.setdefault(f"{r['media_type']}/{r['id']}", candidate(r))
                if len(found) >= KEEP:
                    break
            # Results from the rental's years first, then in TMDB's order.
            ranked = sorted(found.values(), key=lambda c: not (c['year'] and int(c['year']) in years))[:KEEP]
            out.write(json.dumps({
                'id': e['id'], 'title': html.unescape(e['title']['rendered']),
                'format': (e.get('format') or [None])[0], 'shelf': e.get('shelf'),
                'year': (e.get('year') or [None])[0], 'language': ', '.join(e.get('language') or []) or None,
                'description': description, 'rejected': e.get('tmdb_rejected'), 'candidates': ranked,
            }, ensure_ascii=False) + '\n')
            out.flush()
    rows = load_jsonl(CANDIDATES)
    log(f'{len(rows)} rentals in {CANDIDATES}; {sum(1 for r in rows if not r["candidates"])} found nothing on TMDB')

SYSTEM = """You match rentals from Movie Madness, a video store in Portland, Oregon, to entries on TMDB (The Movie Database).

Each rental comes with the store's catalog data and a list of TMDB search results ("candidates"). For each rental, pick the candidate that is the same film or show, or none.

How to read the store's data:
- Titles put leading articles last ("Night Agent, The") and add format and edition in parentheses: "(DVD)", "(Blu-Ray)", "(Criterion)", "(OOP)" for out of print.
- `year` is often the disc's release year, not the film's; a year in the title itself is usually the film's.
- `shelf` is where it sits in the store. A shelf ending in a person's name ("Hollywood Directors > SPIELBERG, STEVEN") names the director or actor.
- `description` is often TMDB's own overview of the film, so a candidate whose overview matches it is very likely right.
- `rejected` is a TMDB id an earlier step found from the store's cover and threw out because the titles didn't fit. The store reuses old pages for new titles, so the cover can belong to another film. Don't pick it unless the title clearly fits.

Rules:
- Pick only from the rental's own candidates. If none is the same work, answer null. A wrong id is worse than none.
- A TV season, volume or disc of a show is that show's tv/ entry.
- A double feature ("A / B") or a collection of several films has no single entry: answer null unless one candidate is the collection itself.
- confidence: "high" when title and at least one of year, language, people or description agree; "low" when you picked but are unsure.
- note: a few words on why, especially for null or low."""

def pick():
    from typing import Literal, Optional
    from pydantic import BaseModel
    import anthropic

    class Pick(BaseModel):
        id: int
        tmdb: Optional[str]
        confidence: Literal['high', 'low']
        note: str

    class Picks(BaseModel):
        picks: list[Pick]

    model, size = arg('--model') or 'claude-haiku-5-5', int(arg('--batch') or 50)
    rows = load_jsonl(CANDIDATES)
    done = {p['id'] for p in load_jsonl(PICKS)}
    todo = [r for r in rows if r['id'] not in done and r['candidates']]   # nothing to pick from: no answer needed
    log(f'{len(rows)} rentals searched; {len(todo)} with candidates to pick with {model}')
    client = anthropic.Anthropic()
    usage = {'input': 0, 'output': 0}
    with open(PICKS, 'a') as out:
        for n in range(0, len(todo), size):
            chunk = todo[n:n + size]
            response = client.messages.parse(
                model=model, max_tokens=16000, system=SYSTEM,
                messages=[{'role': 'user', 'content':
                           'Pick a TMDB id for each of these rentals. Answer for every one, by its id.\n\n'
                           + '\n'.join(json.dumps(r, ensure_ascii=False) for r in chunk)}],
                output_format=Picks)
            usage['input'] += response.usage.input_tokens
            usage['output'] += response.usage.output_tokens
            if response.stop_reason != 'end_turn':
                sys.exit(f'stopped: {response.stop_reason}')
            allowed = {r['id']: {c['tmdb'] for c in r['candidates']} for r in chunk}
            got = 0
            for p in response.parsed_output.picks:
                if p.id not in allowed:
                    continue
                if p.tmdb and p.tmdb not in allowed[p.id]:   # not one of its candidates
                    p.tmdb, p.confidence, p.note = None, 'low', f'picked {p.tmdb}, not a candidate'
                out.write(json.dumps({**p.model_dump(), 'model': model}, ensure_ascii=False) + '\n')
                got += 1
            out.flush()
            log(f'  {n + len(chunk)}/{len(todo)}: {got} answers for {len(chunk)} rentals')
    log(f'tokens: {usage["input"]} in, {usage["output"]} out')

if __name__ == '__main__':
    step = sys.argv[1] if len(sys.argv) > 1 else ''
    {'candidates': find_candidates, 'pick': pick}.get(step, lambda: sys.exit(__doc__))()
