#!/usr/bin/env bash
set -euo pipefail
bash scripts/push-checkpoint.sh 'Checkpoint catalog coverage backfill' data/catalog.json data/games.sqlite data/last-run.json
