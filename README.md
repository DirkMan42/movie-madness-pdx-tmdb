# Movie Madness PDX ↔ TMDB

Which [Movie Madness](https://www.moviemadness.org/) rentals are a given [TMDB](https://www.themoviedb.org/) film or show, and which shelf they're on.

Movie Madness is an independent video store and nonprofit film museum in Portland, Oregon. Its catalog has no public film identifier, so matching it to anything else means searching by title and guessing. These scripts keep a local copy of the catalog, work out each rental's TMDB id and shelf, and write the result as small static JSON files that can be served from GitHub Pages and looked up by TMDB id.

It was built for [mmboxmonkey](https://github.com/tjsander/mmboxmonkey), a userscript that shows Movie Madness availability on Letterboxd film pages.

## The lookup files

`export_api.py` writes them to `api/`:

```
api/index.json                counts, time of the newest site change included, data notice
api/tmdb/movie/NNN.json       every TMDB film id whose last three digits are NNN
api/tmdb/tv/NNN.json          the same for shows
```

NNN is `id % 1000`, zero-padded to three digits. All 2,000 files exist, so a film the store doesn't have is a missing key, not a 404. The Matrix is TMDB film 603, so it is key `"603"` in `tmdb/movie/603.json`:

```json
{"603": [{"id": 22745, "slug": "matrix-the-4k-uhd", "title": "Matrix, The (4K UHD)",
          "format": "4K UHD", "shelf": "Hollywood Dir. > Hollywood Directors", "match": "poster"}]}
```

| Field | |
|---|---|
| `id` | The rental's id on moviemadness.org |
| `slug` | Its page is `https://www.moviemadness.org/?rental=<slug>`. The store reuses old pages for new titles, so a slug can name a different film; use it only as a link |
| `title` | The store's title, with format and edition in parentheses |
| `format` | 4K UHD, Blu-Ray 3D, Blu-Ray, DVD, DVD-R, VHS or Book |
| `shelf` | The permanent shelf, left out when not known |
| `display` | A temporary shelf (New Arrival, Staff Picks, …), left out when it has none |
| `match` | How the TMDB id was found: `poster`, `description`, `credits`, `edition`, `language`, `title` |

About three quarters of the store's ~99,600 rentals have a TMDB id. A rental in the files is in the store's collection; that doesn't mean a copy is on the shelf today.

## How it works

| Script | |
|---|---|
| `fetch_catalog.sh`, `fetch_locations.sh`, `fetch_details.sh`, `fetch_media.py` | First full pass over the store's public WordPress REST API |
| `merge_locations.py`, `merge_details.py` | Turn the API's term ids into names |
| `update_catalog.py` | Daily: only rentals added or changed since the last run |
| `scrape_shelves.py`, `build_shelves.py` | The name-level shelf ("Hollywood Directors > SPIELBERG, STEVEN"), which the API lacks, from the site's search results |
| `resolve_tmdb.py` | TMDB ids: from the store's cover image (a TMDB poster) where it has one, else by description, credits, language, or title and year. Ids whose TMDB titles are nothing like the rental's are dropped |
| `export_api.py` | Writes `api/` |
| `daily_update.sh` | Runs the daily steps in order |

`resolve_tmdb.py` needs a TMDB API Read Access Token in `~/.config/mmboxmonkey/tmdb-token`. The fetched catalog and everything generated from it are ignored by git.

The store's site is a small nonprofit's: the scripts are throttled and resumable, and once caught up the daily update is a handful of requests.

## Data sources & attribution

- **Catalog** (titles, formats, shelf locations): the public [Movie Madness](https://www.moviemadness.org/) rental catalog. This is an unaffiliated fan project, not endorsed by or connected with Movie Madness. If you find this useful, go rent a movie.
- **TMDB ids**: found with the [TMDB](https://www.themoviedb.org/) API. This product uses the TMDB API but is not endorsed or certified by TMDB.

## License

The **code** in this repository is licensed under the [MIT License](LICENSE).

The **catalog data** the code fetches, and anything generated or published from it, is *not* covered by that grant. It is derived from Movie Madness and TMDB and remains subject to their terms — see [NOTICE](NOTICE). Reuse the code freely; clearing reuse of the data is your own responsibility.
