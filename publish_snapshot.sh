#!/bin/bash
set -euo pipefail
cd /Users/servas/college_mdk01_bot
/opt/homebrew/bin/python3 build_snapshot.py
git add docs/archive.enc.json
git commit -m "Update encrypted archive snapshot"
git push origin main
