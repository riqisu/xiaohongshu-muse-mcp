#!/usr/bin/env bash
# Fresh login QR via the OFFICIAL headed login tool (the path that actually
# logged in on 2026-11-23). Use this when the MCP QR path cannot be used
# (e.g. the MCP server is down) or when a scan needs the SMS step handled,
# because this Chrome stays open for the SMS code afterwards.
#
# Kills any previous login-tool run, retries the flaky first status check
# (up to 4 attempts), waits for the QR dialog, screenshots the Xvfb screen
# and crops the QR. Prints the PNG path — VERIFY the crop visually before
# sending it to the user (all three finder patterns + white margin).
# Latest QR is also copied to tests/login-qrcode-latest.png.
#
# Usage: bin/login-qr.sh
# Requires: relay + Xvfb up (bin/start-all.sh). The login tool's own
# CheckLoginStatus exits early if cookies.json already holds a session,
# so to force a fresh QR for another account, back up / clear cookies.json first.
set -u
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1
. ./bin/xhs-env.sh

pkill -f "[x]iaohongshu-login-linux-amd64" 2>/dev/null; sleep 1
FLOW=0
for attempt in 1 2 3 4; do
  echo "attempt $attempt"
  rm -f /tmp/xhs-login-current.log
  ./bin/xiaohongshu-login-linux-amd64 > /tmp/xhs-login-current.log 2>&1 &
  pid=$!
  for _ in $(seq 1 35); do
    sleep 2
    if grep -q "开始登录流程" /tmp/xhs-login-current.log 2>/dev/null; then FLOW=1; break; fi
    if ! kill -0 $pid 2>/dev/null; then break; fi
  done
  if [ $FLOW -eq 1 ]; then echo "login flow started (attempt $attempt, pid $pid)"; break; fi
  kill $pid 2>/dev/null; sleep 2
done
if [ $FLOW -eq 0 ]; then
  echo "FAILED: login flow never started"; tail -5 /tmp/xhs-login-current.log | cut -c1-150
  exit 1
fi
sleep 35
python3 - <<'EOF'
from mss import MSS
from PIL import Image
from datetime import datetime
from pathlib import Path
with MSS() as s:
    s.shot(output='/tmp/xhs-xvfb-qr.png')
im = Image.open('/tmp/xhs-xvfb-qr.png')
stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
out = Path.home() / f'workspace/custom-connectors/custom.xiaohongshu/tests/login-qrcode-live-{stamp}.png'
out.parent.mkdir(parents=True, exist_ok=True)
# QR dialog crop for the 1440x1200 Xvfb screen (verified 2026-11-23)
im.crop((370, 400, 540, 610)).resize((510, 630), Image.LANCZOS).save(out)
latest = out.parent / 'login-qrcode-latest.png'
latest.write_bytes(out.read_bytes())
print(f'qr: {out}')
print(f'latest: {latest}')
EOF
echo "login tool still waiting (pid $pid). Verify the crop visually, then send it."
