#!/bin/sh
# Publishes api/ to the gh-pages branch, which GitHub Pages serves at
# https://tjsander.github.io/movie-madness-pdx-tmdb/. api/ is a worktree of
# that branch (git worktree add api gh-pages), so this commits whatever
# export_api.py changed there and pushes it. Does nothing if nothing changed.
cd "$(dirname "$0")/../api" || exit 1
[ "$(git rev-parse --abbrev-ref HEAD)" = gh-pages ] || { echo "publish: api/ is not a gh-pages worktree"; exit 1; }
git add -A || exit 1
if git diff --cached --quiet; then
  echo "publish: no changes"
else
  git commit -q -m "Catalog as of $(sed -n 's/.*"updated":"\([^"]*\)".*/\1/p' index.json)" || exit 1
  echo "publish: $(git show --stat --format= HEAD | tail -1)"
fi
git push -q origin gh-pages
