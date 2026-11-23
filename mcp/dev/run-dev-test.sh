#!/usr/bin/env bash
# Run the Xiaohongshu dev-platform harness end to end (simulated env).
#
#   bash dev/run-dev-test.sh
#
# Starts the mock server on 127.0.0.1:18100 (restarting any calibration
# instance), checks Xvfb :99 and the Python deps, runs devtest.py
# (T1–T5, PASS/FAIL per case), then stops the mock server. Exits
# non-zero if any test fails. Never touches the live cookies.json or
# the running MCP server (:18060) — all traffic is 127.0.0.1.
set -u
DEV="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$DEV/../.." && pwd)"
SPIDER_VENV="$REPO/vendor/Spider_XHS/.venv/bin/python"
cd "$DEV" || exit 1

# Local traffic only: NO_PROXY keeps the mock (127.0.0.1 / the mock
# hostname) direct. Proxy vars are KEPT (not unset): the Spider signing
# path fetches the real ds endpoint (as.xiaohongshu.com) on first use
# and direct egress fails TLS there, so rednote_api.py needs the egress
# proxy; Chrome ignores the proxy via --no-proxy-server (devtest.py).
export DISPLAY=:99
export NO_PROXY="${NO_PROXY:-},127.0.0.1,localhost,mock.xiaohongshu.com"

# 1) Xvfb :99 (1440x1200, the geometry bin/login-qr.sh crops for)
if pgrep -f "[X]vfb :99" >/dev/null; then
  echo "xvfb: already up (:99)"
else
  echo "xvfb: starting :99"
  nohup Xvfb :99 -screen 0 1440x1200x24 > /tmp/xhs-xvfb-dev.log 2>&1 &
  sleep 2
  pgrep -f "[X]vfb :99" >/dev/null || { echo "xvfb: FAILED"; exit 1; }
fi

# 2) mock server, restarted fresh (any calibration instance is replaced)
pkill -f "[m]ock_xhs.py" 2>/dev/null; sleep 1
"$SPIDER_VENV" mock_xhs.py > /tmp/mock-xhs-dev.log 2>&1 &
MOCK_PID=$!
trap 'kill $MOCK_PID 2>/dev/null' EXIT
ok=0
for _ in $(seq 1 20); do
  if curl -s --max-time 2 http://127.0.0.1:18100/health >/dev/null; then ok=1; break; fi
  sleep 0.5
done
[ "$ok" = 1 ] || { echo "mock server FAILED to start (see /tmp/mock-xhs-dev.log)"; exit 1; }
echo "mock: up on 127.0.0.1:18100 (pid $MOCK_PID)"

# 3) deps (reinstall after a VM restart: pip install -r requirements-dev.txt)
"$SPIDER_VENV" -c "import mss, websocket, cv2, qrcode, PIL; print('deps: ok')" \
  || { echo "deps missing — run: $SPIDER_VENV -m pip install -r requirements-dev.txt"; exit 1; }

# 4) harness (T1–T5)
"$SPIDER_VENV" devtest.py
RC=$?
echo "harness exit=$RC"
exit $RC
