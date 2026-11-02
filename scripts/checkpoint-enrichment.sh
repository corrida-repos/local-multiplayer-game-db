#!/usr/bin/env bash
set -euo pipefail
bash scripts/push-checkpoint.sh 'Checkpoint complete game enrichment and audit' data/enrichment.json data/enrichment-audit.json data/enrichment.sqlite
