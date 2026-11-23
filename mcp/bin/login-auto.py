#!/usr/bin/env python3
"""Automated Xiaohongshu QR login — own the whole wait loop in a script.

Why this exists (2026-11-23: QR / verification-code waits take too
long when the agent hand-steps them): generating a QR, enlarging it,
sending it, polling for the scan, refreshing on expiry and waiting for a
verification code are all mechanical waits. Doing them as agent turns
means minutes of reasoning between steps. This script does all of it and
only prints status lines. The agent's job shrinks to: start it in the
background, send the QR from the state file, report the final result.

Flow (MCP QR path — the one that logged in 2026-11-23 09:25, no SMS):
  for attempt in 1..MAX_ATTEMPTS:
    1. call MCP get_login_qrcode (~35 s, browser launch), save the PNG
    2. enlarge it + white border (MCP QRs are 128x128 with no border and
       are unscannable as sent) and save to a UNIQUE file under
       mcp/tests/ (never reuse a filename — the client caches by path)
    3. write tests/login-auto-state.json {pngPath, generatedAt, deadline,
       attempt, status} so the current live QR can be fetched on demand
    4. print "QR:<path> attempt=n/N deadline=HH:MM:SS" (agent sends it)
    5. poll check_login_status every POLL_S until the deadline:
       "✅ 已登录" -> print LOGIN-OK, state status=ok, exit 0.
       (First check after a login is flaky — retry once on error.)
       Any mention of verification in the status text is logged and the
       wait continues: for the MCP QR flow the verification happens in
       the Xiaohongshu app itself after the scan.
    6. on deadline without login -> print QR-EXPIRED-REFRESHING, next
       attempt. Attempts exhausted -> LOGIN-FAILED, exit 1.

If the login needs an SMS code (the MCP QR path did not on 2026-11-23),
use the headed path instead: mcp/bin/login-qr.sh, then
mcp/bin/submit-sms.py <code> once the code arrives.

Safety: an unscanned QR simply expires. This script never touches
cookies.json and never logs the user out.

Usage:
  python3 mcp/bin/login-auto.py            # normal run, 3 attempts, 240 s per QR
Env overrides:
  XHS_LOGIN_MAX_ATTEMPTS (default 3)
  XHS_LOGIN_QR_TTL_S     (default 240 — the MCP QR lives ~4 min)
  XHS_LOGIN_POLL_S       (default 20)
  XHS_LOGIN_NO_SUCCESS_CHECK=1  # TEST ONLY: skip status checks, exercise
                                # expiry/refresh without needing a scan.
Requires: the stack up (mcp/bin/start-all.sh: relay :8888, Xvfb :99, MCP
:18060). Exits 2 with a clear message if the MCP server is unreachable.
"""
import base64
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["XHS_MCP_TIMEOUT"] = "300"

from client import call_rpc, McpError  # noqa: E402

HERE = Path(__file__).resolve().parent
CONNECTOR_DIR = HERE.parent
TESTS_DIR = CONNECTOR_DIR / "tests"
STATE_PATH = TESTS_DIR / "login-auto-state.json"

MAX_ATTEMPTS = int(os.environ.get("XHS_LOGIN_MAX_ATTEMPTS", "3"))
QR_TTL_S = int(os.environ.get("XHS_LOGIN_QR_TTL_S", "240"))
POLL_S = int(os.environ.get("XHS_LOGIN_POLL_S", "20"))
NO_SUCCESS_CHECK = os.environ.get("XHS_LOGIN_NO_SUCCESS_CHECK") == "1"

UTC = timezone.utc


def log(msg):
    print(msg, flush=True)


def hhmmss(dt):
    return dt.strftime("%H:%M:%S")


def write_state(**fields):
    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    state = {"updatedAt": datetime.now(UTC).isoformat(), **fields}
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    return state


def check_stack():
    try:
        call_rpc("tools/list", {})
        return True
    except Exception as exc:
        log(f"STACK-DOWN: MCP server unreachable ({exc}); run bin/start-all.sh first")
        return False


def fetch_qr_png():
    """Returns (png_bytes or None, server_text). png_bytes is None when the
    server answers without a QR — e.g. '你当前已处于登录状态' when the
    session is already alive (no new QR is issued then)."""
    result = call_rpc("tools/call", {"name": "get_login_qrcode", "arguments": {}})
    if result.get("isError"):
        raise McpError(f"get_login_qrcode failed: {result}")
    png_bytes = None
    text_parts = []
    for item in result.get("content", []):
        if item.get("type") == "image" and item.get("data"):
            png_bytes = base64.b64decode(item["data"])
        elif item.get("type") == "text" and item.get("text"):
            text_parts.append(item["text"])
            m = re.search(r"data:image/png;base64,([A-Za-z0-9+/=]+)", item["text"])
            if m:
                png_bytes = base64.b64decode(m.group(1))
    return png_bytes, "\n".join(text_parts)


def enlarge_and_border(png_bytes, out_path):
    """MCP QRs are ~128x128 with no white border: scale up + add border."""
    from PIL import Image

    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    target = 512
    if max(im.size) < target:
        scale = target / max(im.size)
        im = im.resize((round(im.width * scale), round(im.height * scale)), Image.NEAREST)
    border = 48
    canvas = Image.new("RGB", (im.width + 2 * border, im.height + 2 * border), "white")
    canvas.paste(im, (border, border))
    canvas.save(out_path)
    return out_path


def check_logged_in():
    """True if the MCP reports a logged-in session. Retry once: the first
    check after a login is flaky (observed 2026-11-23)."""
    for attempt in (1, 2):
        try:
            result = call_rpc("tools/call", {"name": "check_login_status", "arguments": {}})
        except Exception as exc:
            log(f"POLL-STATUS check-error attempt={attempt}: {exc}")
            time.sleep(5)
            continue
        text = ""
        for item in result.get("content", []):
            if item.get("type") == "text":
                text += item.get("text", "")
        if "✅ 已登录" in text or "已登录" in text:
            m = re.search(r"用户名[:：]\s*(\S+)", text)
            return True, (m.group(1) if m else "")
        if "验证" in text or "verify" in text.lower():
            log(f"POLL-STATUS verification-mentioned: {text[:120]}")
        return False, text[:120]
    return False, "check-error"


def main():
    TESTS_DIR.mkdir(parents=True, exist_ok=True)  # QR + state live here;
    # mcp/tests/ does not exist on a fresh clone, and the first QR save
    # happens before write_state() (the only other mkdir).
    if not check_stack():
        return 2
    if not NO_SUCCESS_CHECK:
        ok, username = check_logged_in()
        if ok:
            log(f"LOGIN-OK already-logged-in username={username or '?'}")
            return 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            png_bytes, server_text = fetch_qr_png()
        except Exception as exc:
            log(f"QR-ERROR attempt={attempt}/{MAX_ATTEMPTS}: {exc}")
            if attempt == MAX_ATTEMPTS:
                write_state(status="failed", reason=str(exc)[:200])
                log("LOGIN-FAILED: could not generate a QR code")
                return 1
            time.sleep(5)
            continue
        if png_bytes is None:
            if "已处于登录状态" in server_text or "已登录" in server_text:
                ok, username = check_logged_in()
                if ok:
                    log(f"LOGIN-OK already-logged-in username={username or '?'}")
                    return 0
            log(f"QR-ERROR attempt={attempt}/{MAX_ATTEMPTS}: no QR image in MCP response: {server_text[:200]}")
            if attempt == MAX_ATTEMPTS:
                write_state(status="failed", reason="no QR image in MCP response")
                log("LOGIN-FAILED: could not generate a QR code")
                return 1
            time.sleep(5)
            continue
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = TESTS_DIR / f"xiaohongshu-qrcode-{stamp}.png"
        enlarge_and_border(png_bytes, out_path)
        # The QR is generated during the fetch call (~35 s browser launch),
        # so its server-side clock is already running when we get it back.
        # Treat it as expiring 45 s early so we never show a dead QR.
        deadline = datetime.now(UTC) + timedelta(seconds=max(30, QR_TTL_S - 45))
        write_state(
            pngPath=str(out_path),
            generatedAt=datetime.now(UTC).isoformat(),
            deadline=deadline.isoformat(),
            attempt=attempt,
            maxAttempts=MAX_ATTEMPTS,
            status="waiting",
        )
        log(f"QR:{out_path} attempt={attempt}/{MAX_ATTEMPTS} deadline={hhmmss(deadline)}")
        while datetime.now(UTC) < deadline:
            if NO_SUCCESS_CHECK:
                time.sleep(min(POLL_S, max(1, (deadline - datetime.now(UTC)).total_seconds())))
                continue
            ok, info = check_logged_in()
            if ok:
                write_state(status="ok", username=info)
                log(f"LOGIN-OK username={info or '?'}")
                return 0
            log(f"POLL-STATUS waiting attempt={attempt} info={info[:80]}")
            time.sleep(POLL_S)
        log(f"QR-EXPIRED-REFRESHING attempt={attempt}/{MAX_ATTEMPTS}")
    write_state(status="failed", reason="QR expired on all attempts")
    log(f"LOGIN-FAILED: QR code expired {MAX_ATTEMPTS} times — login aborted")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
