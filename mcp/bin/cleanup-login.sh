#!/usr/bin/env bash
# Close leftover headed-login Chrome after a login round (2026-11-23).
#
# Problem: the headed login tool (xiaohongshu-login-linux-amd64) spawns a
# rod Chrome that survives after the tool exits. Its DevToolsActivePort
# file stays in /tmp/rod/user-data/*, and submit-sms.py then picks the
# STALE Chrome (arbitrary glob order) and submits the SMS code to the
# wrong browser — the code expires while the real dialog waits.
#
# Fix: kill the login tool + every rod Chrome (matched by its
# /tmp/rod user-data dir, so the MCP server binary itself is untouched),
# then remove the stale profile dirs so no dead port file can be picked
# up again. Safe at rest: the MCP server's browser is per-call and
# discarded, so no Chrome should be running outside a login round.
#
# Usage:
#   bin/cleanup-login.sh            # after a login round finishes
# It is also called automatically at the start of bin/login-qr.sh.
set -u
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1

pkill -f "[x]iaohongshu-login-linux-amd64" 2>/dev/null
pkill -f "[/]tmp/rod" 2>/dev/null
sleep 1
if pgrep -f "[/]tmp/rod" >/dev/null 2>&1; then
  echo "cleanup: a rod Chrome is still running, stale profile dirs kept"
  exit 1
fi
rm -rf /tmp/rod/user-data/* 2>/dev/null
echo "cleanup: login tool + rod Chrome closed, stale profiles removed"
