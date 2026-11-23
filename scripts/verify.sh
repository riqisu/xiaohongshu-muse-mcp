#!/usr/bin/env bash
# Smoke-test the logged-in Xiaohongshu route. Run after login.
# Exits non-zero if any step fails. Prints only counts/titles, never cookies.
set -eu
cd "$(dirname "$0")/.."
PY="vendor/Spider_XHS/.venv/bin/python"
echo "== login =="
"$PY" spider/rednote_api.py me
echo "== search =="
"$PY" spider/rednote_api.py search "10分钟快手菜" | head -n 8
echo "== collections (first page) =="
"$PY" spider/rednote_api.py collect | head -n 15
echo "verify: OK"
