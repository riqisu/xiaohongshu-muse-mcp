#!/usr/bin/env python3
"""Submit an SMS verification code to the Xiaohongshu login dialog in the
headed Chrome (rod browser) via CDP — fast path, ~5 s end to end.

The login tool's Chrome exposes a DevTools port written to
/tmp/rod/user-data/*/DevToolsActivePort (port changes every run, so it is
discovered here, never hardcoded). This script finds the page, clears any
old code, clicks the SMS input, types the code with real input events
(React-safe), checks the value + Verify button state, and clicks Verify.

Usage: python3 bin/submit-sms.py <4-8 digit code>
Requires: the headed login tool waiting at the SMS dialog (bin/login-qr.sh),
websocket-client + a running Xvfb Chrome. The code is typically valid for
~5 minutes and the account rate-limits after 3 failed submits, so send it
immediately after it arrives.
"""
import glob
import json
import os
import sys
import time
import urllib.request

import websocket

SMS_PLACEHOLDER = "请输入验证码"


def find_page_ws_list():
    """DevTools targets, newest Chrome first.

    /tmp/rod/user-data/*/DevToolsActivePort files are sorted by mtime
    descending, so a leftover Chrome from a previous login round is never
    picked before the current one (2026-11-23: the first submit went to
    the stale Chrome and the 5-minute SMS code expired while the real
    dialog waited). Dead ports (Chrome already closed) are skipped.
    """
    files = sorted(
        glob.glob("/tmp/rod/user-data/*/DevToolsActivePort"),
        key=lambda f: os.path.getmtime(f), reverse=True)
    out = []
    for f in files:
        try:
            port = open(f).readline().strip()
        except OSError:
            continue
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as r:
                targets = json.load(r)
        except Exception:
            continue
        for t in targets:
            if t.get("type") == "page" and (
                "xiaohongshu.com" in t.get("url", "") or "rednote.com" in t.get("url", "")
            ):
                out.append(t["webSocketDebuggerUrl"])
    return out


def main():
    code = sys.argv[1].strip()
    assert code.isdigit() and 4 <= len(code) <= 8, "code must be 4-8 digits"
    candidates = find_page_ws_list()
    if not candidates:
        print("error: no Xiaohongshu Chrome DevTools target found (is login-qr.sh running?)",
              file=sys.stderr)
        return 1
    ws = None
    send = ev = None
    for ws_url in candidates:
        try:
            ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
        except Exception:
            continue
        mid = [0]

        def send(method, params):
            mid[0] += 1
            i = mid[0]
            ws.send(json.dumps({"id": i, "method": method, "params": params}))
            while True:
                r = json.loads(ws.recv())
                if r.get("id") == i:
                    return r

        def ev(expr):
            return send("Runtime.evaluate", {"expression": expr, "returnByValue": True})

        # Confirm the SMS dialog is actually open on THIS page before
        # typing into it — the dialog closes on its own, and a stale
        # Chrome has no input at all.
        r = ev("""
(() => {
  const inp = [...document.querySelectorAll('input')].find(e => e.placeholder === '%s');
  return inp ? 'SMS-OPEN' : 'NO SMS INPUT';
})()
""" % SMS_PLACEHOLDER)
        if r.get("result", {}).get("result", {}).get("value") == "SMS-OPEN":
            print("sms dialog open on this Chrome, proceeding")
            break
        ws.close()
        ws = None
    if ws is None:
        print("error: found Chrome(s) but none has the SMS dialog open "
              "(did it close on its own? run bin/login-qr.sh for a fresh QR)",
              file=sys.stderr)
        return 1

    def click(x, y):
        for t in ("mousePressed", "mouseReleased"):
            send("Input.dispatchMouseEvent",
                 {"type": t, "x": x, "y": y, "button": "left", "clickCount": 1})
            time.sleep(0.15)
        time.sleep(0.3)

    # 1) clear any old code via the native setter (React-safe)
    ev("""
(() => {
  const inp = [...document.querySelectorAll('input')].find(e => e.placeholder === '%s');
  if (!inp) return 'NO SMS INPUT';
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(inp, '');
  inp.dispatchEvent(new Event('input', {bubbles: true}));
  return 'cleared';
})()
""" % SMS_PLACEHOLDER)
    time.sleep(1.0)  # let React re-render / layout settle before measuring
    # 2) fresh rect, real click, real typing
    r = ev("""
(() => {
  const inp = [...document.querySelectorAll('input')].find(e => e.placeholder === '%s');
  if (!inp) return 'NO SMS INPUT';
  const b = inp.getBoundingClientRect();
  return JSON.stringify({x: b.x + b.width / 2, y: b.y + b.height / 2, val: inp.value});
})()
""" % SMS_PLACEHOLDER)
    val = r["result"]["result"]["value"]
    if val == "NO SMS INPUT":
        print("error: SMS dialog closed between probe and typing — get a fresh QR",
              file=sys.stderr)
        ws.close()
        return 1
    info = json.loads(val)
    print("input:", info)
    click(info["x"], info["y"])
    send("Input.insertText", {"text": code})
    time.sleep(0.5)
    # 3) verify value + button enabled, then submit
    r = ev("""
(() => {
  try {
    const inp = [...document.querySelectorAll('input')].find(e => e.placeholder === '%s');
    const btn = [...document.querySelectorAll('button, div')].find(e => e.textContent.trim() === '验证' && e.getBoundingClientRect().width > 0);
    const bb = btn.getBoundingClientRect();
    return JSON.stringify({val: inp.value, btnCls: btn.className, btn: {x: bb.x + bb.width / 2, y: bb.y + bb.height / 2}});
  } catch (e) { return 'ERR: ' + e.message; }
})()
""" % SMS_PLACEHOLDER)
    st = json.loads(r["result"]["result"]["value"])
    print("after typing:", st)
    if st.get("val") == code and st.get("btn") and "btn-disabled" not in (st.get("btnCls") or ""):
        click(st["btn"]["x"], st["btn"]["y"])
        print("verify clicked")
    else:
        print("ABORTED - input/button state wrong, did not submit")
        ws.close()
        return 1
    ws.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
