"""Spider_XHS SMS login driver (mirrors XHSLoginApi.phone_login, but the
phone code arrives via chat instead of stdin).

Run in background. Writes:
- sms-status.json: {stage, ...} (init_device / sending_code / code_sent /
  verifying / done / failed / timeout)
- sms-result.json: {ok, nickname, red_id, user_id, search_ok, ...} on finish
- spider-cookies.txt: cookie string on success (DO NOT share)

The 6-digit code the user sends in chat is written to sms-code.txt by the
agent; this driver picks it up, uses it once, and deletes the file.
Read-only afterwards: one test search to verify a real (non-guest) login.
No publish/like/comment.
"""
import json
import os
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor" / "Spider_XHS"))

from apis.xhs_pc_apis import XHS_Apis
from apis.xhs_pc_login_apis import XHSLoginApi
from xhs_utils.xhs_pc import XHSPcAuth

BASE = str(Path(__file__).resolve().parent)
PHONE = os.environ["XHS_PHONE"]  # digits only, e.g. a China mobile number
ZONE = os.environ.get("XHS_PHONE_ZONE", "86")
CODE_FILE = f"{BASE}/sms-code.txt"


def status(stage, **extra):
    with open(f"{BASE}/sms-status.json", "w") as f:
        json.dump({"stage": stage, "ts": time.time(), **extra}, f, ensure_ascii=False)


def main():
    login = XHSLoginApi()
    status("init_device")
    print("[1/4] initializing anonymous device...", flush=True)
    cookies = login.generate_init_cookies()
    login.ensure_webprofile(cookies)

    status("sending_code")
    print("[2/4] sending SMS code...", flush=True)
    success, msg, _ = login.send_phone_code(PHONE, cookies, zone=ZONE)
    if not success:
        status("failed", reason=f"send code failed: {msg}")
        print("FAILED send code:", msg, flush=True)
        return 1
    print("[2/4] code sent", flush=True)
    status("code_sent", sent_at=time.time())

    deadline = time.time() + 300
    code = None
    while time.time() < deadline:
        if os.path.exists(CODE_FILE):
            code = open(CODE_FILE).read().strip()
            if code:
                break
        time.sleep(2)
    if not code:
        status("timeout", reason="no code received in 300s")
        print("FAILED: no code in 300s", flush=True)
        return 1
    try:
        os.remove(CODE_FILE)
    except OSError:
        pass

    status("verifying")
    print("[3/4] verifying code...", flush=True)
    success, msg, result = login.login_by_phone(PHONE, code, cookies, zone=ZONE)
    if not success:
        status("failed", reason=f"verify failed: {msg}")
        print("FAILED verify:", msg, flush=True)
        return 1
    cookies = result["cookies"]

    success, user_info, cookies = login.get_user_info(cookies)
    if not success or user_info.get("guest") is not False:
        status("failed", reason=f"guest session rejected: {user_info}")
        print("FAILED: guest session", user_info, flush=True)
        return 1
    print("user: logged in (guest=False)", flush=True)

    cookies_str = login.cookies_to_str(cookies)
    with open(f"{BASE}/spider-cookies.txt", "w") as f:
        f.write(cookies_str)

    auth = XHSPcAuth.from_cookie(cookies_str)
    api = XHS_Apis(auth)
    ok, msg, res = api.search_note("10分钟快手菜", page=1)
    items = (((res or {}).get("data") or {}).get("items") or [])
    result = {
        "ok": True,
        "search_ok": ok,
        "search_msg": msg,
        "search_items": len(items),
    }
    with open(f"{BASE}/sms-result.json", "w") as f:
        json.dump(result, f, ensure_ascii=False)
    status("done", **result)
    print("DONE:", json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
