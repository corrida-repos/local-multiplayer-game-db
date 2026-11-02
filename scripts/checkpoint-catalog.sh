#!/usr/bin/env bash
set -euo pipefail
git add data/
if ! git diff --cached --quiet; then
  git commit -m 'Checkpoint catalog coverage backfill'
  git pull --rebase origin main
  git push origin HEAD:main
fi
