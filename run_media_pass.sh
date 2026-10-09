#!/bin/sh
# One-off: fetch every rental's poster name and description, then resolve the
# posters to TMDB ids. Resumable; logs to media.log.
cd "$(dirname "$0")" || exit 1
{
  echo "=== $(date '+%F %T') media pass"
  python3 fetch_media.py --window 01:00-07:00 && python3 resolve_tmdb.py
} >> media.log 2>&1
