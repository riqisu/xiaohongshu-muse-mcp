#!/usr/bin/env python3
"""Mock Xiaohongshu — a SIMULATED environment for local dev/testing.

Serves, on 127.0.0.1:18100 only:
  * a mock login page (GET /login) that replays the real login flow with
    the same DOM the real scripts expect: a QR code (login QR -> security
    verify QR -> SMS dialog with <input placeholder="请输入验证码"> and a
    验证 button -> success page). Stage transitions are SERVER-driven
    (elapsed time vs. the chaos knobs), the page just polls /state and
    renders. This reproduces the real countdowns without a real scan,
    a real SMS code, or Xiaohongshu risk control.
  * mock API endpoints mimicking webapi.rednote.com: user/me, search,
    note feed, collect page. The session class comes from the
    web_session cookie value (see _session_class): logged-in, guest,
    or expired. Error classes mirror the real ones: guest search -104,
    wrong-domain/expired note -100 "登录已过期", mismatched xsec_token
    300031 "当前笔记暂时无法浏览", empty collect xsec_token -1.
  * GET /state?sid=... — server-side truth for the harness (stage,
    expected SMS code, what was submitted, verify status).
  * GET /health — {"ok": true}.

Chaos knobs (query params on /login, per session):
  qr_autoscan=N      seconds the login QR stays up (default 6)
  verify_autoscan=N  seconds the security QR stays up (default 5)
  verify_ttl=N       security QR expiry; if it fires first the flow
                     refreshes back to a new login QR (default 60)
  sms_ttl=N          SMS code validity (default 300)
  sms_autoclose=N    SMS dialog auto-closes N seconds after it opens
                     (0 = never; default 0)
  code=NNNNNN        the "SMS code" the harness reads from /state
                     (default 123456)

Never serves anything but 127.0.0.1. Never touches the live cookies.json
or the running MCP server. All values here are fake (mock-*).
"""
import io
import json
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import qrcode

HOST = "127.0.0.1"
PORT = 18100

# ---------------------------------------------------------------- mock data
MOCK_USER = {
    "guest": False,
    "user_id": "mock-user-001",
    "nickname": "MockUser麦田",
    "red_id": "mockred001",
    "xsec_token": "MOCK_XSEC_USER",
    "desc": "模拟账号：本地开发平台专用",
    "gender": 0,
}
MOCK_NOTES = {
    "mock-note-001": {
        "title": "Mock快手菜：蒜蓉西兰花",
        "desc": "蒜蓉西兰花：西兰花切小朵焯水2分钟捞出；蒜末爆香，加生抽、蚝油翻炒均匀即可。",
        "xsec_token": "MOCK_XSEC_NOTE_1",
        "nickname": "Mock夏夏",
        "liked_count": 1234,
        "images": ["https://mock.invalid/img/001-a.jpg",
                   "https://mock.invalid/img/001-b.jpg"],
    },
    "mock-note-002": {
        "title": "Mock快手菜：酸辣土豆丝",
        "desc": "酸辣土豆丝：土豆切丝泡水去淀粉；干辣椒、花椒爆香，大火快炒，加醋、生抽。",
        "xsec_token": "MOCK_XSEC_NOTE_2",
        "nickname": "Mock夏夏",
        "liked_count": 987,
        "images": ["https://mock.invalid/img/002-a.jpg"],
    },
}

# ---------------------------------------------------------------- sessions
SESSIONS = {}
# RLock (not Lock): /sms-submit holds it while calling current_stage(),
# which takes it again — a plain Lock deadlocks the whole server there
# (found by the harness: every /state poll timed out after the first
# SMS submit). RLock is reentrant, so the nested take is safe.
LOCK = threading.RLock()


def _cfg(params):
    def f(name, default):
        try:
            return float(params.get(name, [default])[0])
        except (TypeError, ValueError):
            return float(default)
    return {
        "qr_autoscan": f("qr_autoscan", 6),
        "verify_autoscan": f("verify_autoscan", 5),
        "verify_ttl": f("verify_ttl", 60),
        "sms_ttl": f("sms_ttl", 300),
        "sms_autoclose": f("sms_autoclose", 0),
        "code": params.get("code", ["123456"])[0],
    }


def get_session(sid, params=None):
    with LOCK:
        s = SESSIONS.get(sid)
        if s is None:
            s = {
                "sid": sid,
                "cfg": _cfg(params or {}),
                "created": time.time(),
                "stage": "qr",
                "stage_since": time.time(),
                "qr_refreshes": 0,
                "sms_submitted": None,
                "sms_submit_count": 0,
                "verified": False,
            }
            SESSIONS[sid] = s
        return s


def current_stage(s):
    """Advance the server-side stage machine by elapsed time. The page
    polls /state and renders whatever this returns."""
    with LOCK:
        if s["verified"]:
            return "success"
        now = time.time()
        stage, since = s["stage"], s["stage_since"]
        cfg = s["cfg"]
        if stage == "qr" and now - since >= cfg["qr_autoscan"]:
            s["stage"], s["stage_since"] = "verify", now
            stage = "verify"
        if stage == "verify":
            if now - since >= cfg["verify_ttl"]:
                # Security QR expired before it was "scanned": refresh
                # back to a fresh login QR (real behaviour).
                s["stage"], s["stage_since"] = "qr", now
                s["qr_refreshes"] += 1
                stage = "qr"
            elif now - since >= cfg["verify_autoscan"]:
                s["stage"], s["stage_since"] = "sms", now
                stage = "sms"
        if stage == "sms":
            ac = cfg["sms_autoclose"]
            if ac and now - since >= ac:
                s["stage"] = "closed"
                stage = "closed"
            elif now - since >= cfg["sms_ttl"]:
                s["stage"] = "closed"
                stage = "closed"
        return stage


def session_state(sid):
    s = get_session(sid)
    stage = current_stage(s)
    with LOCK:
        return {
            "sid": sid,
            "stage": stage,
            "code": s["cfg"]["code"],
            "sms_submitted": s["sms_submitted"],
            "sms_submit_count": s["sms_submit_count"],
            "verified": s["verified"],
            "qr_refreshes": s["qr_refreshes"],
            "elapsed": round(time.time() - s["created"], 1),
        }


# ---------------------------------------------------------------- QR images
def qr_png(payload):
    qr = qrcode.QRCode(border=0, box_size=4)
    qr.add_data(payload)
    qr.make()
    im = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- API
def _session_class(handler):
    """Logged-in / guest / expired, from the web_session cookie value."""
    raw = handler.headers.get("Cookie", "")
    c = SimpleCookie()
    try:
        c.load(raw)
    except Exception:
        pass
    ws = c.get("web_session")
    v = ws.value if ws else ""
    if v == "mock-web-session":
        return "logged-in"
    if v == "mock-guest-session":
        return "guest"
    return "expired"


def _ok(data):
    return {"code": 0, "success": True, "msg": "成功", "data": data}


def _err(code, msg):
    return {"code": code, "success": False, "msg": msg, "data": {}}


def api_user_me(handler):
    cls = _session_class(handler)
    if cls == "logged-in":
        return _ok(dict(MOCK_USER))
    if cls == "guest":
        return _ok({"guest": True, "user_id": "", "xsec_token": ""})
    return _err(-100, "登录已过期")


def api_search_notes(handler, body):
    cls = _session_class(handler)
    if cls != "logged-in":
        return _err(-104, "登录已过期" if cls == "expired" else "未登录")
    items = []
    for nid, n in MOCK_NOTES.items():
        items.append({
            "id": nid,
            # xsec_token lives at ITEM level in the real v2 search payload;
            # rednote_api.py builds the original post link from it.
            "xsec_token": n["xsec_token"],
            "note_card": {
                "display_title": n["title"],
                "desc": n["desc"],
                "user": {"nickname": n["nickname"], "user_id": "mock-user-002"},
                "interact_info": {"liked_count": n["liked_count"]},
                "image_list": [{"url": u} for u in n["images"]],
            },
        })
    return _ok({"items": items, "has_more": False})


def api_feed(handler, body):
    cls = _session_class(handler)
    if cls != "logged-in":
        return _err(-100, "登录已过期")
    nid = (body or {}).get("source_note_id", "")
    xt = (body or {}).get("xsec_token", "")
    n = MOCK_NOTES.get(nid)
    if n is None:
        return _err(-100, "登录已过期")
    if xt != n["xsec_token"]:
        # Same as the real 300031: the user/me xsec_token (or any other
        # note's token) does not open this note.
        return _err(300031, "当前笔记暂时无法浏览")
    return _ok({"items": [{
        "id": nid,
        "note_card": {
            "display_title": n["title"],
            "desc": n["desc"],
            "user": {"nickname": n["nickname"], "user_id": "mock-user-002"},
            "interact_info": {"liked_count": n["liked_count"]},
            "image_list": [{"url": u} for u in n["images"]],
        },
    }]})


def api_collect_page(handler, query):
    cls = _session_class(handler)
    if cls != "logged-in":
        return _err(-104, "未登录")
    if not query.get("xsec_token", [""])[0]:
        return _err(-1, "薯队长遇到一些小麻烦")
    notes = [{
        "note_id": nid,
        "display_title": n["title"],
        "xsec_token": n["xsec_token"],
        "user": {"nickname": n["nickname"]},
    } for nid, n in MOCK_NOTES.items()]
    return _ok({"notes": notes, "has_more": False, "cursor": ""})


# ---------------------------------------------------------------- pages
LOGIN_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Mock 小红书登录</title>
<style>
  body { margin:0; background:#fff; font-family:sans-serif; }
  /* QR / SMS controls are fixed-positioned so the screenshot crop used
     by bin/login-qr.sh (370,400,540,610 on the 1440x1200 Xvfb screen)
     captures them. Calibrated 2026-11-23: Chrome UI (tab strip +
     toolbar + host-resolver-rules infobar) offsets page coords by
     +173px vertically, so page top:245 lands at screen y 418..548,
     inside the crop with margin on all sides. */
  #qr-img { position:fixed; left:390px; top:245px; width:130px; height:130px;
            image-rendering:pixelated; }
  #dlg-title { position:fixed; left:390px; top:205px; width:200px;
               font-size:18px; color:#333; }
  #dlg-hint { position:fixed; left:390px; top:390px; width:200px;
              font-size:13px; color:#888; }
  #sms-input { position:fixed; left:390px; top:245px; width:170px; height:40px;
               font-size:16px; padding:4px 8px; box-sizing:border-box; }
  #verify-btn { position:fixed; left:390px; top:305px; width:170px; height:40px;
                font-size:16px; background:#ff2442; color:#fff; border:0;
                border-radius:6px; cursor:pointer; }
  #sms-msg { position:fixed; left:390px; top:360px; width:200px;
             font-size:13px; color:#c00; }
  #login-success { position:fixed; left:390px; top:245px; font-size:22px; color:#090; }
</style></head><body>
<div id="dlg-title"></div>
<img id="qr-img" style="display:none">
<div id="dlg-hint"></div>
<input id="sms-input" style="display:none" placeholder="请输入验证码">
<button id="verify-btn" style="display:none">验证</button>
<div id="sms-msg"></div>
<div id="login-success" style="display:none">登录成功（模拟）</div>
<script>
const SID = new URLSearchParams(location.search).get('sid') || 'default';
const qrImg = document.getElementById('qr-img');
const title = document.getElementById('dlg-title');
const hint = document.getElementById('dlg-hint');
const smsInput = document.getElementById('sms-input');
const verifyBtn = document.getElementById('verify-btn');
const smsMsg = document.getElementById('sms-msg');
const success = document.getElementById('login-success');
let lastStage = '';
function show(el, on) { el.style.display = on ? '' : 'none'; }
async function poll() {
  try {
    const r = await fetch('/state?sid=' + encodeURIComponent(SID));
    const st = await r.json();
    if (st.stage === lastStage) return;
    lastStage = st.stage;
    show(qrImg, false); show(smsInput, false); show(verifyBtn, false);
    show(success, false); smsMsg.textContent = '';
    if (st.stage === 'qr') {
      title.textContent = '扫码登录（模拟）';
      hint.textContent = '请使用小红书 App 扫码（模拟）';
      qrImg.src = '/qr?sid=' + encodeURIComponent(SID) + '&kind=login&t=' + Date.now();
      show(qrImg, true);
    } else if (st.stage === 'verify') {
      title.textContent = '安全验证（模拟）';
      hint.textContent = '请再次扫码完成安全验证（模拟）';
      qrImg.src = '/qr?sid=' + encodeURIComponent(SID) + '&kind=verify&t=' + Date.now();
      show(qrImg, true);
    } else if (st.stage === 'sms') {
      title.textContent = '短信验证（模拟）';
      hint.textContent = '验证码已发送（模拟）';
      show(smsInput, true); show(verifyBtn, true);
    } else if (st.stage === 'closed') {
      title.textContent = '短信验证（模拟）';
      hint.textContent = '短信框已关闭（模拟超时）';
      // The real dialog unmounts on close (React): remove the controls
      // from the DOM, don't just hide them. submit-sms.py probes for
      // a VISIBLE input (fixed 2026-11-23) and fails cleanly if the
      // dialog closes mid-submit — a display:none input must not
      // count as open.
      smsInput.remove(); verifyBtn.remove();
    } else if (st.stage === 'success') {
      title.textContent = '';
      show(success, true);
    }
  } catch (e) { /* server briefly away; retry next tick */ }
}
verifyBtn.addEventListener('click', async () => {
  const code = smsInput.value.trim();
  try {
    const r = await fetch('/sms-submit?sid=' + encodeURIComponent(SID), {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({code})});
    const res = await r.json();
    if (res.ok) { poll(); } else { smsMsg.textContent = '验证码错误（模拟）'; }
  } catch (e) { smsMsg.textContent = '提交失败（模拟）'; }
});
setInterval(poll, 400);
poll();
</script></body></html>
"""

DECOY_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Mock 小红书首页</title></head>
<body style="font-family:sans-serif"><h1>Mock 小红书首页（诱饵页，无短信框）</h1>
<p>笔记 1：Mock快手菜：蒜蓉西兰花</p><p>笔记 2：Mock快手菜：酸辣土豆丝</p></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # keep the log quiet; harness asserts via /state

    def _send(self, status, body, ctype="application/json"):
        if isinstance(body, bytes):
            data = body
        elif isinstance(body, str):
            data = body.encode()  # HTML pages pass through verbatim
        else:
            data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw.decode() or "{}")
        except Exception:
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/health":
            return self._send(200, {"ok": True})
        if u.path == "/login":
            sid = q.get("sid", ["default"])[0]
            s = get_session(sid, q)
            with LOCK:
                # (Re)configure from the page's query params and restart
                # the stage machine: the harness polls /state before the
                # page loads, which creates the session with DEFAULT cfg
                # — without this reset a ?sms_autoclose=4 would be lost
                # and the dialog would never close (T3 failure).
                s["cfg"] = _cfg(q)
                s["created"] = time.time()
                s["stage"] = "qr"
                s["stage_since"] = time.time()
                s["qr_refreshes"] = 0
                s["sms_submitted"] = None
                s["sms_submit_count"] = 0
                s["verified"] = False
            return self._send(200, LOGIN_PAGE, "text/html; charset=utf-8")
        if u.path == "/decoy":
            return self._send(200, DECOY_PAGE, "text/html; charset=utf-8")
        if u.path == "/qr":
            sid = q.get("sid", ["default"])[0]
            kind = q.get("kind", ["login"])[0]
            payload = f"mock://xhs-login?sid={sid}&kind={kind}"
            return self._send(200, qr_png(payload), "image/png")
        if u.path == "/state":
            sid = q.get("sid", ["default"])[0]
            return self._send(200, session_state(sid))
        if u.path == "/api/sns/web/v2/user/me":
            return self._send(200, api_user_me(self))
        if u.path == "/api/sns/web/v2/note/collect/page":
            return self._send(200, api_collect_page(self, q))
        self._send(404, {"code": 404, "success": False, "msg": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/sms-submit":
            sid = q.get("sid", ["default"])[0]
            s = get_session(sid)
            body = self._read_json()
            code = str(body.get("code", "")).strip()
            with LOCK:
                s["sms_submit_count"] += 1
                if current_stage(s) != "sms":
                    return self._send(200, {"ok": False, "error": "no-dialog"})
                if code != s["cfg"]["code"]:
                    return self._send(200, {"ok": False, "error": "wrong-code"})
                s["sms_submitted"] = code
                s["verified"] = True
            return self._send(200, {"ok": True})
        body = self._read_json()
        if u.path == "/api/sns/web/v2/search/notes":
            return self._send(200, api_search_notes(self, body))
        if u.path == "/api/sns/web/v1/feed":
            return self._send(200, api_feed(self, body))
        self._send(404, {"code": 404, "success": False, "msg": "not found"})


if __name__ == "__main__":
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"mock-xhs listening on http://{HOST}:{PORT} (127.0.0.1 only)", flush=True)
    srv.serve_forever()
