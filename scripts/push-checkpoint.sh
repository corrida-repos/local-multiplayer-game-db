#!/usr/bin/env bash
# A commit may already exist after a failed push: always reconcile and retry it.
set -euo pipefail
checkpoint_message=$1
shift
git add -- "$@"
if ! git diff --cached --quiet; then git commit -m "$checkpoint_message"; fi
for attempt in 1 2 3 4 5; do
  if git pull --rebase origin main && git push origin HEAD:main; then exit 0; fi
  sleep "$attempt"
done
exit 1
