#!/bin/bash
# Pages the catalog again for each entry's format, rating, year, genre and language
# term ids, plus the term tables that name them (resumable).
mkdir -p "$(dirname "$0")/../data/catalog-details/terms" && cd "$(dirname "$0")/../data/catalog-details" || exit 1
UA='Mozilla/5.0 (X11; Linux x86_64) mmboxmonkey-test'
for tax in format rating date genre language; do
  for p in 1 2; do
    f=terms/$tax$p.json
    [ -s "$f" ] && continue
    curl -s -f -A "$UA" "https://www.moviemadness.org/wp-json/wp/v2/$tax?per_page=100&page=$p&_fields=id,name,slug,parent,count" -o "$f" || rm -f "$f"
    sleep 0.4
  done
done
for p in $(seq 1 996); do
  f=page$p.json
  [ -s "$f" ] && continue
  for try in 1 2 3; do
    curl -s -f -A "$UA" "https://www.moviemadness.org/wp-json/wp/v2/rental?per_page=100&page=$p&_fields=id,format,rating,date,genre,language" -o "$f" && break
    sleep 5
  done
  sleep 0.4
done
echo done
