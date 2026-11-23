"""Spider_XHS QR login driver (mirrors XHSLoginApi.qrcode_login, but saves
the QR as a PNG for the user to scan, and saves the resulting cookies).

Run in background. Writes:
- qr-login.png : QR code to scan with the Xiaohongshu app
- qr-status.json: {stage, qr_url, created_at, deadline, ...}
- spider-cookies.txt: cookie string on success (DO NOT share)
- qr-result.json: {ok, nickname, red_id, user_id, search_ok, ...} on finish

Read-only afterwards: one test search to verify the session is a real
(non-guest) login. No publish/like/comment.
"""
import json
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor" / "Spider_XHS"))

from apis.xhs_pc_apis import XHS_Apis
from apis.xhs_pc_login_apis import XHSLoginApi
from xhs_utils.xhs_pc import XHSPcAuth

BASE = str(Path(__file__).resolve().parent)


def status(stage, **extra):
    with open(f"{BASE}/qr-status.json", "w") as f:
        json.dump({"stage": stage, "ts": time.time(), **extra}, f, ensure_ascii=False)


def main():
    login = XHSLoginApi()
    status("init_device")
    print("[1/5] initializing anonymous device...", flush=True)
    cookies = login.generate_init_cookies()

    status("get_qrcode")
    print("[2/5] getting QR code...", flush=True)
    success, msg, qr_data = login.generate_qrcode(cookies)
    if not success:
        status("failed", reason=f"get qrcode failed: {msg}")
        print("FAILED get qrcode:", msg, flush=True)
        return 1
    cookies = qr_data["cookies"]
    qr_url = qr_data["qr_url"]
    print("qr_url:", qr_url, flush=True)

    status("precheck")
    print("[3/5] pre-check + webprofile...", flush=True)
    success, msg, cookies = login.check_qrcode_status(
        qr_data["qr_id"], qr_data["code"], cookies
    )
    if success or msg != "请扫描二维码":
        status("failed", reason=f"precheck abnormal: {msg}")
        print("FAILED precheck:", msg, flush=True)
        return 1
    login.ensure_webprofile(cookies)

    # Save QR as PNG for the user.
    import qrcode

    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(qr_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(f"{BASE}/qr-login.png")
    deadline = time.time() + 180
    status("waiting_scan", qr_url=qr_url, deadline=deadline)
    print("[4/5] QR saved, waiting for scan (180s)...", flush=True)

    while time.time() < deadline:
        try:
            success, msg, cookies = login.check_qrcode_status(
                qr_data["qr_id"], qr_data["code"], cookies
            )
        except Exception as e:
            status("failed", reason=f"poll error: {e}")
            print("FAILED poll error:", e, flush=True)
            return 1
        print("poll:", msg, flush=True)
        if success:
            break
        if msg == "二维码已过期":
            status("expired", reason="QR expired")
            print("FAILED: QR expired", flush=True)
            return 1
        time.sleep(2)
    else:
        status("timeout", reason="waited 180s, no scan")
        print("FAILED: timeout waiting for scan", flush=True)
        return 1

    status("verify")
    print("[5/5] verifying real login...", flush=True)
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
    with open(f"{BASE}/qr-result.json", "w") as f:
        json.dump(result, f, ensure_ascii=False)
    status("done", **result)
    print("DONE:", json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
