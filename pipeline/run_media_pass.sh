#!/bin/sh
# One-off: fetch every rental's poster name and description, then resolve the
# posters to TMDB ids. Resumable; logs to media.log.
mkdir -p "$(dirname "$0")/../data" && cd "$(dirname "$0")/../data" || exit 1
{
  echo "=== $(date '+%F %T') media pass"
  python3 ../pipeline/fetch_media.py --window 01:00-07:00 && python3 ../pipeline/resolve_tmdb.py
} >> media.log 2>&1
