#!/usr/bin/env bash
set -euo pipefail
git add data/composites.json data/composites.sqlite
if ! git diff --cached --quiet; then
  git commit -m 'Update console-specific rating composites'
  for attempt in 1 2 3 4; do
    git pull --rebase origin main
    if git push origin HEAD:main; then exit 0; fi
  done
  exit 1
fi
