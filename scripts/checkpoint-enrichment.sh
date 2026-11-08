#!/usr/bin/env bash
set -euo pipefail
bash scripts/push-checkpoint.sh 'Checkpoint complete game enrichment and audit' data/enrichment.json data/enrichment-public.json data/media-public.json data/enrichment-audit.json data/enrichment.sqlite data/nindie-index.json data/community-index.json data/recovery-state.json data/nintendo-index.json data/direct-review-index.json data/coverage-baseline.json
