#!/bin/sh
# Weekly: merge the site's catalog changes, then find shelves for new and moved
# titles. Run by the mm-catalog-weekly systemd user timer; logs to update.log.
cd "$(dirname "$0")" || exit 1
{
  echo "=== $(date '+%F %T') weekly update"
  python3 update_catalog.py &&
    python3 build_shelves.py > /dev/null &&
    python3 scrape_shelves.py --ids changed-ids.txt --no-location &&
    python3 build_shelves.py | sed -n '/^entries:/,$p'
} >> update.log 2>&1
