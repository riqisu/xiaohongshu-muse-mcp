"""Rednote API via Spider_XHS local signing -- the route that actually works.

Why this exists (2026-11-23, verified live):
  MCP login lands on rednote.com, not xiaohongshu.com. The MCP cookies.json
  therefore holds TWO sessions: a guest session for .xiaohongshu.com
  (user/me -> guest:true, search -> -104) and the REAL session for
  .rednote.com (id_token, a different web_session). Sending the rednote
  cookie VALUES to edith.xiaohongshu.com fails with -100 "login expired"
  -- cookies are domain-scoped, the server checks the web_session issued
  for that domain. The fix is to send the rednote cookies to the rednote
  API host instead: https://webapi.rednote.com, with Spider's local
  signing. There user/me returns guest:false for the logged-in account,
  and v2 search + collect page work.

Two Spider quirks worked around here:
  1. XHSPcAuth.from_cookie() immediately calls XHS_Apis.bootstrap(),
     which hits edith.xiaohongshu.com user/me. Rednote cookies fail that
     call (-100), so from_cookie raises before any webapi request.
     Workaround: patch bootstrap to a no-op for construction, then set
     the real user_id from a webapi user/me call.
  2. The collect page needs the xsec_token from user/me (empty token
     returns code -1 "薯队长遇到一些小麻烦"). Fetch it first, then pass it.

Read-only except where noted. Never print cookie values: this script only
prints names/counts and API results.

Usage (from this directory, .venv python):
  .venv/bin/python rednote_api.py me
  .venv/bin/python rednote_api.py search "10分钟快手菜"
  .venv/bin/python rednote_api.py collect [--all]
  .venv/bin/python rednote_api.py note <note_id> <xsec_token>

Cookies source: the MCP login's cookies.json (see XHS_COOKIES_JSON below).
Refresh by re-logging in via the MCP QR flow; do NOT copy cookie values
into any other file, and never commit cookies.json.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor" / "Spider_XHS"))

import apis.xhs_pc_apis as _apis_mod

# See module docstring quirk 1: from_cookie bootstraps against edith,
# which rejects rednote cookies. No-op it; we bootstrap against webapi.
_apis_mod.XHS_Apis.bootstrap = lambda self, proxies=None: self

from apis.xhs_pc_apis import XHS_Apis  # noqa: E402
from xhs_utils.xhs_pc import XHSPcAuth  # noqa: E402
from xhs_utils.xhs_pc.params import (  # noqa: E402
    generate_search_id,
    generate_search_session_id,
    splice_str,
)

WEBAPI = "https://webapi.rednote.com"
# Path to the MCP login's cookies.json. Set XHS_COOKIES_JSON to override;
# default assumes this repo sits next to the MCP checkout (see setup.sh).
MCP_COOKIES = Path(os.environ.get(
    "XHS_COOKIES_JSON",
    str(Path(__file__).resolve().parent.parent / "mcp" / "cookies.json"),
))


def note_url(note_id, xsec_token=""):
    """Original post link (open in browser / Xiaohongshu app).

    Every result should carry its original link so the reader can open
    the source directly. The per-note xsec_token comes from the search
    result / share link; without it the plain explore URL still opens
    public notes.
    """
    base = f"https://www.xiaohongshu.com/explore/{note_id}"
    if xsec_token:
        return f"{base}?xsec_token={xsec_token}&xsec_source=pc_search"
    return base


def _rednote_cookies():
    data = json.loads(MCP_COOKIES.read_text())
    out = {}
    for c in data.get("cookies", []):
        if c.get("domain", "").endswith("rednote.com"):
            if c["name"] not in out or c.get("domain") == ".rednote.com":
                out[c["name"]] = c["value"]
    return out


def make_api():
    """Auth with rednote cookies; user_id filled from webapi user/me."""
    cookies = _rednote_cookies()
    assert "a1" in cookies and "web_session" in cookies, "rednote cookies missing a1/web_session"
    auth = XHSPcAuth.from_cookie("; ".join(f"{k}={v}" for k, v in cookies.items()))
    api = XHS_Apis(auth)
    me = user_me(api)
    uid = ((me or {}).get("data") or {}).get("user_id") or ""
    assert uid, "webapi user/me did not return a user_id"
    auth.set_user_id(uid)
    return api, me


def _signed(api, method, path, target=WEBAPI, data="", params=None):
    full = splice_str(path, params) if params else path
    headers, wire, body = api._request_params(full, data, method, target_origin=target)
    if method == "GET":
        resp = api.http.get(target + full, headers=headers, cookies=wire,
                            proxies=api._proxies(None), timeout=30)
    else:
        resp = api.http.post(target + full, headers=headers, data=body,
                             cookies=wire, proxies=api._proxies(None), timeout=30)
    return resp.json()


def user_me(api):
    return _signed(api, "GET", "/api/sns/web/v2/user/me")


def search(api, query, page=1, page_size=20):
    body = {
        "keyword": query, "page": page, "page_size": page_size,
        "search_id": generate_search_id(), "sort": "general", "note_type": 0,
        "ext_flags": [], "geo": "",
        "image_formats": ["jpg", "webp", "avif"],
        "session_id": generate_search_session_id(),
    }
    return _signed(api, "POST", "/api/sns/web/v2/search/notes", data=body)


def collect_page(api, user_id, xsec_token, cursor=""):
    return _signed(api, "GET", "/api/sns/web/v2/note/collect/page", params={
        "num": "30", "cursor": cursor, "user_id": user_id,
        "image_formats": "jpg,webp,avif",
        "xsec_token": xsec_token, "xsec_source": "pc_search",
    })


def note_info(api, note_id, xsec_token):
    return _signed(api, "POST", "/api/sns/web/v1/feed", data={
        "source_note_id": note_id,
        "image_formats": ["jpg", "webp", "avif"],
        "extra": {"need_body_topic": "1"},
        "xsec_source": "pc_search",
        "xsec_token": xsec_token,
    })


def _show_search(res):
    items = ((res or {}).get("data") or {}).get("items") or []
    print(f"search: code={res.get('code')} success={res.get('success')} items={len(items)}")
    for it in items:
        nc = it.get("note_card") or {}
        user = nc.get("user") or {}
        print(f"- {nc.get('display_title')} | {user.get('nickname')} | "
              f"likes={(nc.get('interact_info') or {}).get('liked_count')} | id={it.get('id')} | "
              f"{note_url(it.get('id'), it.get('xsec_token') or '')}")


def main(argv):
    if len(argv) < 2:
        print(__doc__.split("Usage")[1].strip())
        return 2
    api, me = make_api()
    d = (me or {}).get("data") or {}
    print(f"logged in as {d.get('nickname')} (guest={d.get('guest')}, user_id={d.get('user_id')})")
    cmd = argv[1]
    if cmd == "me":
        print(json.dumps(me, ensure_ascii=False)[:600])
    elif cmd == "search":
        _show_search(search(api, argv[2] if len(argv) > 2 else "10分钟快手菜"))
    elif cmd == "collect":
        uid = d["user_id"]
        xt = d.get("xsec_token") or ""
        total = 0
        cursor = ""
        while True:
            res = collect_page(api, uid, xt, cursor)
            notes = ((res or {}).get("data") or {}).get("notes") or []
            print(f"collect page: code={res.get('code')} notes={len(notes)} "
                  f"has_more={((res or {}).get('data') or {}).get('has_more')}")
            for n in notes:
                print(f"- {n.get('display_title')} | {(n.get('user') or {}).get('nickname')} | id={n.get('note_id')} | "
                      f"{note_url(n.get('note_id'), n.get('xsec_token') or '')}")
            total += len(notes)
            cursor = str(((res or {}).get("data") or {}).get("cursor") or "")
            if "--all" not in argv or not ((res or {}).get("data") or {}).get("has_more") or not notes:
                break
        print(f"total collected shown: {total}")
    elif cmd == "note":
        res = note_info(api, argv[2], argv[3] if len(argv) > 3 else "")
        print(f"original: {note_url(argv[2], argv[3] if len(argv) > 3 else '')}")
        print(json.dumps(res, ensure_ascii=False)[:4000])
    else:
        print(f"unknown command: {cmd}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
