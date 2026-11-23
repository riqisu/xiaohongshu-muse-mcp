#!/usr/bin/env bash
# Start the Xiaohongshu stack, idempotently: relay -> Xvfb -> MCP server.
# Safe to run again: anything already running is left alone.
# Logs: /tmp/xhs-relay.log, /tmp/xhs-xvfb.log, /tmp/xhs-mcp.log
set -u
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1
. ./bin/xhs-env.sh

if ! command -v Xvfb >/dev/null 2>&1; then
  echo "ERROR: Xvfb not installed (wiped by a VM restart?). Run: apt-get install -y xvfb"
  exit 1
fi

# 1) relay on 127.0.0.1:8888
if pgrep -f "[r]elay.py" >/dev/null && curl -s -o /dev/null --max-time 5 -x http://127.0.0.1:8888 https://example.com; then
  echo "relay: already up (127.0.0.1:8888)"
else
  pkill -f "[r]elay.py" 2>/dev/null; sleep 1
  nohup python3 bin/relay.py > /tmp/xhs-relay.log 2>&1 &
  sleep 2
  if curl -s -o /dev/null --max-time 10 -x http://127.0.0.1:8888 https://example.com; then
    echo "relay: started"
  else
    echo "relay: FAILED to start, see /tmp/xhs-relay.log"
    exit 1
  fi
fi

# 2) Xvfb virtual screen :99, 1440x1200 (the headed login tool needs a display)
if pgrep -f "[X]vfb :99" >/dev/null; then
  echo "xvfb: already up (:99)"
else
  nohup Xvfb :99 -screen 0 1440x1200x24 > /tmp/xhs-xvfb.log 2>&1 &
  sleep 2
  if pgrep -f "[X]vfb :99" >/dev/null; then echo "xvfb: started"; else echo "xvfb: FAILED"; exit 1; fi
fi

# 3) MCP server on :18060 (Streamable HTTP, no auth)
if curl -s -o /dev/null --max-time 5 http://127.0.0.1:18060/mcp; then
  echo "mcp: already up (:18060)"
else
  pkill -f "[x]iaohongshu-mcp-linux-amd64" 2>/dev/null; sleep 1
  nohup ./bin/xiaohongshu-mcp-linux-amd64 -port :18060 > /tmp/xhs-mcp.log 2>&1 &
  sleep 6
  if curl -s -o /dev/null --max-time 5 http://127.0.0.1:18060/mcp; then
    echo "mcp: started"
  else
    echo "mcp: FAILED to start, see /tmp/xhs-mcp.log"
    exit 1
  fi
fi

echo "all up: relay :8888, xvfb :99, mcp :18060"
