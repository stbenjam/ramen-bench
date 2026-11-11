#!/bin/bash
set -euo pipefail
rm -f /logs/verifier/reward.json /logs/verifier/reward.txt
python3 /tests/check.py --artifact /app/index.html --output /logs/verifier
