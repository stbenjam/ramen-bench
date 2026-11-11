#!/bin/bash
set -euo pipefail
rm -f /logs/verifier/{reward,reward-details,ctrf}.json
start=$(date +%s%3N)
PYTHONPATH=/tests rewardkit /tests --workspace /app --output /logs/verifier/reward.json
python3 /tests/ctrf.py --start "$start"
