#!/usr/bin/env bash
set -euo pipefail
bash scripts/push-checkpoint.sh 'Update console-specific rating composites' data/composites.json data/composites.sqlite
