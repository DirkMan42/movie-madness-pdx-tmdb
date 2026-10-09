#!/bin/sh
# Daily: merge the site's catalog changes, find shelves for new and moved
# titles, and update the Obsidian vault in ~/Movie Madness. Run by the
# mm-catalog-daily systemd user timer; logs to update.log.
cd "$(dirname "$0")" || exit 1
{
  echo "=== $(date '+%F %T') daily update"
  python3 update_catalog.py &&
    python3 build_shelves.py > /dev/null &&
    python3 scrape_shelves.py --ids changed-ids.txt --no-location &&
    python3 build_shelves.py | sed -n '/^entries:/,$p' &&
    python3 resolve_tmdb.py &&
    python3 export_vault.py "$HOME/Movie Madness"
} >> update.log 2>&1
