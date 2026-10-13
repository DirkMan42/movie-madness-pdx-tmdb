#!/bin/sh
# Daily: merge the site's catalog changes, find shelves and TMDB ids for new
# and moved titles, and write the lookup files to api/. Logs to update.log.
cd "$(dirname "$0")" || exit 1
{
  echo "=== $(date '+%F %T') daily update"
  python3 update_catalog.py &&
    python3 build_shelves.py > /dev/null &&
    python3 scrape_shelves.py --ids changed-ids.txt --no-location &&
    python3 build_shelves.py | sed -n '/^entries:/,$p' &&
    python3 resolve_tmdb.py &&
    python3 export_api.py
} >> update.log 2>&1
