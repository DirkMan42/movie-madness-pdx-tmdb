#!/bin/bash
cd "$(dirname "$0")" && mkdir -p catalog && cd catalog
for p in $(seq 1 996); do
  f=page$p.json
  [ -s "$f" ] && continue
  for try in 1 2 3; do
    curl -s -f "https://www.moviemadness.org/wp-json/wp/v2/rental?per_page=100&page=$p&_fields=id,slug,title,location,format,rating,date,genre,language" -o "$f" && break
    sleep 5
  done
  sleep 0.4
done
echo done
