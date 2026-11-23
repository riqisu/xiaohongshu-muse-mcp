#!/usr/bin/env python3
"""End-to-end harness for the Xiaohongshu dev platform (simulated env).

Runs the REAL login/search scripts against the mock server in dev/ —
no real QR scan, no real SMS code, no Xiaohongshu risk control, and
never the live cookies.json or the running MCP server (:18060).

What it exercises (each prints PASS/FAIL; exit 1 if any FAIL):
  T1 full mock login round: QR crop decodes -> submit-sms.py delivers
     the code -> Verify clicks -> success page -> cleanup leaves no
     rod Chrome and no stale /tmp/rod profiles.
  T2 stale Chrome: a decoy Chrome (NEWER profile, a xiaohongshu page
     WITHOUT the SMS dialog) + the current mock Chrome; submit-sms.py
     must skip the decoy and use the one with the dialog.
  T3 dialog closed: submit after the mock auto-closes the SMS dialog
     -> clean exit 1, clear error, no crash, no submit.
  T4 mock API: me guest:false; search returns items WITH the original
     post link; note with the note's OWN xsec_token returns full text +
     images; note with a wrong xsec_token returns 300031; note with a
     guest/expired cookie returns -100; guest search returns -104.
  T5 QR decode: raw 128x128 (no border) does NOT decode with OpenCV;
     the same QR enlarged to 608x608 + white border (the real
     login-auto.py function) DOES decode.

Usage: bash run-dev-test.sh   (starts the mock server, runs this, stops it)
Requires: Xvfb :99 up, rod Chrome at ~/.cache/xiaohongshu-mcp/browser/,
Spider venv python (this file runs under it).
"""
import glob
import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

DEV = Path(__file__).resolve().parent
CONNECTOR = DEV.parent
BIN = CONNECTOR / "bin"
REPO = CONNECTOR.parent
# Spider venv (built by setup.sh) and rednote_api.py, repo-relative.
# The live connector uses its own Spider_XHS layout instead.
VENV_PY = REPO / "vendor/Spider_XHS/.venv/bin/python"
REDNOTE_API = REPO / "spider/rednote_api.py"
MOCK_BASE = "http://127.0.0.1:18100"
MOCK_HOST = "http://mock.xiaohongshu.com:18100"
CHROME_GLOB = str(Path.home() / ".cache/xiaohongshu-mcp/browser/*/browser/chrome")
CROP = (370, 400, 540, 610)  # same as bin/login-qr.sh, 1440x1200 Xvfb

os.environ["DISPLAY"] = ":99"
# Proxy env, saved here: the Spider signing path fetches the real ds
# endpoint (https://as.xiaohongshu.com/...) on first use. If your
# network needs an egress proxy, it needs the *_proxy vars; direct
# egress may fail TLS there. Restored for the rednote_api.py
# subprocess below; the mock API calls (127.0.0.1) bypass the proxy
# via NO_PROXY. Do NOT strip proxy vars here: run-dev-test.sh removed
# them once and that broke the ds fetch.
_PROXY_ENV = {k: v for k, v in os.environ.items()
              if k.lower().endswith("_proxy")}
_cur_no_proxy = os.environ.get("NO_PROXY", "")
os.environ["NO_PROXY"] = ",".join(
    [p for p in (_cur_no_proxy, "127.0.0.1,localhost,mock.xiaohongshu.com") if p])

RESULTS = []
CHROMES = []  # Popen handles launched by this harness


def log(msg):
    print(msg, flush=True)


def record(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    log(f"{'PASS' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))


def run(cmd, timeout=90, env=None, cwd=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=timeout, env=e, cwd=cwd)
    return p.returncode, p.stdout, p.stderr


def rod_chrome():
    hits = sorted(glob.glob(CHROME_GLOB))
    return hits[-1] if hits else None


def mock_state(sid):
    with urllib.request.urlopen(f"{MOCK_BASE}/state?sid={sid}", timeout=5) as r:
        return json.load(r)


def wait_stage(sid, want, timeout=45):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            st = mock_state(sid)
            last = st["stage"]
            if last == want:
                return st
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"sid={sid} stage never reached {want} (last={last})")


def launch_chrome(profile, port, url):
    chrome = rod_chrome()
    assert chrome, "rod Chrome not found under ~/.cache/xiaohongshu-mcp/browser/"
    args = [
        chrome,
        f"--user-data-dir={profile}",
        f"--remote-debugging-port={port}",
        "--host-resolver-rules=MAP mock.xiaohongshu.com 127.0.0.1",
        "--no-proxy-server",
        "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
        "--no-first-run", "--no-default-browser-check",
        "--disable-background-networking",
        "--window-size=1440,1200", "--window-position=0,0",
        url,
    ]
    env = dict(os.environ)
    p = subprocess.Popen(args, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    CHROMES.append(p)
    # This Chromium build does NOT write DevToolsActivePort (verified
    # 2026-11-23: the file never appears even though :port answers).
    # submit-sms.py discovers Chrome ONLY via that file, so the harness
    # writes it — same format Chrome uses (port on line 1). The file's
    # mtime is the launch order T2 relies on (decoy written later).
    Path(profile).mkdir(parents=True, exist_ok=True)
    (Path(profile) / "DevToolsActivePort").write_text(f"{port}\n")
    # Wait for the DevTools HTTP endpoint, not the file.
    for _ in range(60):
        if p.poll() is not None:
            raise RuntimeError(f"Chrome exited early (rc={p.poll()})")
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                if r.status == 200:
                    return p
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("Chrome DevTools endpoint never answered")


def cleanup_login():
    rc, out, _ = run(["bash", str(BIN / "cleanup-login.sh")], timeout=30)
    return rc, out.strip()


def no_rod_left():
    rc, _, _ = run(["pgrep", "-f", "/tmp/rod"], timeout=10)
    profiles = glob.glob("/tmp/rod/user-data/*")
    return rc != 0 and not profiles


def screenshot_crop_decode(run_dir, tag, sid, kind):
    """Same steps as bin/login-qr.sh: mss shot -> crop -> resize -> the
    real login-auto.py enlarge+border -> OpenCV decode."""
    from mss import MSS
    from PIL import Image
    import cv2
    stamp = datetime.now().strftime("%H%M%S")
    full = run_dir / f"{tag}-full-{stamp}.png"
    with MSS() as s:
        s.shot(output=str(full))
    im = Image.open(full)
    crop = im.crop(CROP).resize((510, 630), Image.LANCZOS)
    crop_path = run_dir / f"{tag}-crop-{stamp}.png"
    crop.save(crop_path)
    spec = importlib.util.spec_from_file_location(
        "login_auto", str(BIN / "login-auto.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    big_path = run_dir / f"{tag}-crop-608-{stamp}.png"
    mod.enlarge_and_border(crop_path.read_bytes(), str(big_path))
    det = cv2.QRCodeDetector()
    data, _, _ = det.detectAndDecode(cv2.imread(str(big_path)))
    return data, str(crop_path), str(big_path)


def submit_sms(code):
    return run([str(VENV_PY), str(BIN / "submit-sms.py"), code],
               timeout=90, cwd=str(BIN))


def rednote_api(args, cookies_file):
    env = {
        "XHS_WEBAPI_BASE": MOCK_BASE,
        "XHS_COOKIES_JSON": str(cookies_file),
        # ds fetch (real as.xiaohongshu.com) needs the egress proxy;
        # mock calls to 127.0.0.1 bypass it via NO_PROXY.
        **_PROXY_ENV,
    }
    return run([str(VENV_PY), str(REDNOTE_API)] + args,
               timeout=90, env=env, cwd=str(REPO / "spider"))


def mock_api(method, path, cookie=None, body=None):
    req = urllib.request.Request(
        MOCK_BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Content-Type": "application/json",
                 **({"Cookie": cookie} if cookie else {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


# ---------------------------------------------------------------- tests
def test_t1(run_dir, stamp):
    name = "T1 full mock login round"
    try:
        sid = f"t1-{stamp}"
        profile = f"/tmp/rod/user-data/mock-t1-{stamp}"
        launch_chrome(profile, 19001,
                      f"{MOCK_HOST}/login?sid={sid}&qr_autoscan=8&verify_autoscan=5&code=123456")
        wait_stage(sid, "qr", timeout=25)
        time.sleep(1.5)  # let the QR render
        data, _, _ = screenshot_crop_decode(run_dir, "t1", sid, "login")
        want = f"mock://xhs-login?sid={sid}&kind=login"
        assert data == want, f"QR crop decoded {data!r}, want {want!r}"
        st = wait_stage(sid, "sms", timeout=40)
        code = st["code"]
        rc, out, err = submit_sms(code)
        assert rc == 0 and "verify clicked" in out, \
            f"submit-sms rc={rc} out={out!r} err={err!r}"
        st = wait_stage(sid, "success", timeout=20)
        assert st["sms_submitted"] == code, f"sms_submitted={st['sms_submitted']!r}"
        rc, out = cleanup_login()
        assert no_rod_left(), "rod Chrome or stale profiles left after cleanup"
        record(name, True, f"QR decoded, code {code} submitted, success, cleanup clean")
    except Exception as e:
        record(name, False, str(e))


def test_t2(run_dir, stamp):
    name = "T2 stale Chrome skipped (decoy is newer)"
    try:
        sid = f"t2-{stamp}"
        profile = f"/tmp/rod/user-data/mock-t2-{stamp}"
        launch_chrome(profile, 19001,
                      f"{MOCK_HOST}/login?sid={sid}&qr_autoscan=8&verify_autoscan=5&code=123456")
        wait_stage(sid, "sms", timeout=40)
        # Decoy AFTER the real one: its DevToolsActivePort mtime is newer,
        # so the old (pre-fix) picker would have taken the decoy first.
        dprofile = f"/tmp/rod/user-data/decoy-t2-{stamp}"
        launch_chrome(dprofile, 19002, f"{MOCK_HOST}/decoy")
        time.sleep(1)
        rc, out, err = submit_sms("123456")
        assert rc == 0 and "verify clicked" in out, \
            f"submit-sms rc={rc} out={out!r} err={err!r}"
        st = mock_state(sid)
        assert st["stage"] == "success", f"mock stage={st['stage']!r}, code went to the decoy?"
        rc, out = cleanup_login()
        assert no_rod_left(), "rod Chrome or stale profiles left after cleanup"
        record(name, True, "submit went to the Chrome with the SMS dialog")
    except Exception as e:
        record(name, False, str(e))


def test_t3(run_dir, stamp):
    name = "T3 submit after SMS dialog auto-closed"
    try:
        sid = f"t3-{stamp}"
        profile = f"/tmp/rod/user-data/mock-t3-{stamp}"
        launch_chrome(profile, 19001,
                      f"{MOCK_HOST}/login?sid={sid}&qr_autoscan=5&verify_autoscan=3"
                      "&sms_autoclose=4&code=123456")
        wait_stage(sid, "closed", timeout=30)
        # Let the page notice (it polls /state every 400 ms) and hide
        # the input before submitting. Without this settle, the submit
        # can race the dialog closing mid-flight — submit-sms.py used
        # to crash with an unhandled JSONDecodeError in step 3 (the
        # input vanishes between the probe and the verify-state read).
        # Fixed 2026-11-23: the probe requires a VISIBLE input and
        # step 3 fails cleanly on a non-JSON result.
        time.sleep(1.5)
        rc, out, err = submit_sms("123456")
        assert rc == 1, f"submit-sms rc={rc}, want 1 (no dialog)"
        assert "none has the SMS dialog open" in err, f"stderr={err!r}"
        assert "Traceback" not in err, f"submit-sms crashed: {err!r}"
        rc, out = cleanup_login()
        assert no_rod_left(), "rod Chrome or stale profiles left after cleanup"
        record(name, True, "clean exit 1, no crash, no submit")
    except Exception as e:
        record(name, False, str(e))


def test_t4(run_dir, stamp):
    name = "T4 mock API (me/search/note/collect + error classes)"
    try:
        li = DEV / "mock-cookies-loggedin.json"
        guest = "a1=mock-a1-guest; web_session=mock-guest-session"
        expired = "a1=mock-a1-expired; web_session=mock-expired-session"
        rc, out, err = rednote_api(["me"], li)
        assert rc == 0 and "guest=False" in out and "MockUser麦田" in out, \
            f"me rc={rc} out={out!r} err={err!r}"
        rc, out, err = rednote_api(["search", "快手菜"], li)
        assert rc == 0 and "items=2" in out, f"search rc={rc} out={out!r}"
        assert "蒜蓉西兰花" in out and "酸辣土豆丝" in out, f"search titles: {out!r}"
        link1 = ("https://www.xiaohongshu.com/explore/mock-note-001"
                 "?xsec_token=MOCK_XSEC_NOTE_1&xsec_source=pc_search")
        assert link1 in out, f"original link missing from search: {out!r}"
        rc, out, err = rednote_api(["note", "mock-note-001", "MOCK_XSEC_NOTE_1"], li)
        assert rc == 0 and f"original: {link1}" in out, f"note rc={rc} out={out!r}"
        assert "蒜蓉西兰花：西兰花切小朵焯水2分钟" in out, f"note full text: {out!r}"
        assert "https://mock.invalid/img/001-a.jpg" in out, f"note images: {out!r}"
        rc, out, err = rednote_api(["note", "mock-note-001", "WRONGTOKEN"], li)
        assert rc == 0 and "300031" in out, f"wrong xsec_token rc={rc} out={out!r}"
        rc, out, err = rednote_api(["collect"], li)
        assert rc == 0 and "notes=2" in out and link1 in out, \
            f"collect rc={rc} out={out!r}"
        me_g = mock_api("GET", "/api/sns/web/v2/user/me", cookie=guest)
        assert me_g.get("data", {}).get("guest") is True, f"guest me: {me_g!r}"
        feed_g = mock_api("POST", "/api/sns/web/v1/feed", cookie=guest,
                          body={"source_note_id": "mock-note-001",
                                "xsec_token": "MOCK_XSEC_NOTE_1"})
        assert feed_g.get("code") == -100, f"guest feed: {feed_g!r}"
        feed_e = mock_api("POST", "/api/sns/web/v1/feed", cookie=expired,
                          body={"source_note_id": "mock-note-001",
                                "xsec_token": "MOCK_XSEC_NOTE_1"})
        assert feed_e.get("code") == -100, f"expired feed: {feed_e!r}"
        search_g = mock_api("POST", "/api/sns/web/v2/search/notes", cookie=guest,
                            body={"keyword": "快手菜"})
        assert search_g.get("code") == -104, f"guest search: {search_g!r}"
        record(name, True, "me/search/note/collect OK; -100/-104/300031 reproduced")
    except Exception as e:
        record(name, False, str(e))


def test_t5(run_dir, stamp):
    name = "T5 QR decode: raw 128 fails, enlarged 608 decodes"
    try:
        import qrcode
        import cv2
        import importlib.util as iu
        # Short payload on purpose: the real MCP QR encodes a short login
        # code, so a short payload matches its module density. A long
        # payload (e.g. with a timestamp in the sid) makes a denser QR
        # whose bicubic 128x128 downscale blurs past recovery — the
        # enlarged version then fails to decode for the wrong reason.
        payload = "mock://xhs-login?sid=t5&kind=login"
        qr = qrcode.QRCode(border=0, box_size=4)
        qr.add_data(payload)
        qr.make()
        raw = run_dir / f"t5-raw128-{stamp}.png"
        qr.make_image(fill_color="black", back_color="white").resize((128, 128)).save(raw)
        det = cv2.QRCodeDetector()
        data_raw, _, _ = det.detectAndDecode(cv2.imread(str(raw)))
        assert data_raw == "", f"raw 128 decoded unexpectedly: {data_raw!r}"
        spec = iu.spec_from_file_location("login_auto", str(BIN / "login-auto.py"))
        mod = iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        big = run_dir / f"t5-608-{stamp}.png"
        mod.enlarge_and_border(raw.read_bytes(), str(big))
        data_big, _, _ = det.detectAndDecode(cv2.imread(str(big)))
        assert data_big == payload, f"enlarged decoded {data_big!r}, want {payload!r}"
        record(name, True, "raw 128: no decode; enlarged 608: decodes")
    except Exception as e:
        record(name, False, str(e))


def main():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = DEV / "runs" / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    log(f"dev harness run {stamp} (artifacts: {run_dir})")
    try:
        with urllib.request.urlopen(f"{MOCK_BASE}/health", timeout=5) as r:
            assert json.load(r).get("ok"), "mock /health not ok"
    except Exception as e:
        log(f"FAIL mock server not up on {MOCK_BASE}: {e}")
        return 1
    if not rod_chrome():
        log("FAIL rod Chrome not found under ~/.cache/xiaohongshu-mcp/browser/")
        return 1
    rc, out = cleanup_login()
    log(f"pre-cleanup: {out}")
    try:
        test_t1(run_dir, stamp)
        test_t2(run_dir, stamp)
        test_t3(run_dir, stamp)
        test_t4(run_dir, stamp)
        test_t5(run_dir, stamp)
    finally:
        # Never leave a test Chrome behind, even on failure.
        for p in CHROMES:
            try:
                if p.poll() is None:
                    p.terminate()
            except Exception:
                pass
        cleanup_login()
        for p in CHROMES:
            try:
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
    failed = [r for r in RESULTS if not r[1]]
    log(f"--- {len(RESULTS) - len(failed)}/{len(RESULTS)} passed ---")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
