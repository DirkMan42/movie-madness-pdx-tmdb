#!/bin/sh
# Daily: merge the site's catalog changes, find shelves and TMDB ids for new
# and moved titles, and write the lookup files to api/. Logs to update.log.
mkdir -p "$(dirname "$0")/../data" && cd "$(dirname "$0")/../data" || exit 1
{
  echo "=== $(date '+%F %T') daily update"
  python3 ../pipeline/update_catalog.py &&
    python3 ../pipeline/build_shelves.py > /dev/null &&
    python3 ../pipeline/scrape_shelves.py --ids changed-ids.txt --no-location &&
    python3 ../pipeline/build_shelves.py | sed -n '/^entries:/,$p' &&
    python3 ../pipeline/resolve_tmdb.py &&
    python3 ../pipeline/export_api.py ../api
} >> update.log 2>&1
