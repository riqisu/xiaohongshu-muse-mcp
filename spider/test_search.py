"""Test: Spider_XHS search with the MCP's saved cookies.
Read-only: calls user/me (bootstrap) + search_note once. No publish/like/comment.

NOTE: this is the OLD xiaohongshu.com route. It is expected to return
code -104 (guest session) now that login lands on rednote.com -- see
rednote_api.py for the working route (webapi.rednote.com).
"""
import json
import sys
from pathlib import Path

import os
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor" / "Spider_XHS"))

from apis.xhs_pc_apis import XHS_Apis
from xhs_utils.xhs_pc import XHSPcAuth

MCP_COOKIES = os.environ.get("XHS_COOKIES_JSON", "../mcp/cookies.json")

with open(MCP_COOKIES) as f:
    data = json.load(f)

# cookies.json holds BOTH .xiaohongshu.com and .rednote.com values for the
# same names (a1, web_session, ...) with DIFFERENT values. trans_cookies()
# collapses duplicates into a dict (last wins), so mixing both domains sends
# the rednote values to xiaohongshu.com APIs -> "登录已过期". Keep only the
# xiaohongshu.com ones, preferring the bare-domain (.xiaohongshu.com) value.
xhs = [c for c in data.get("cookies", [])
       if c.get("domain", "").endswith("xiaohongshu.com")]
by_name = {}
for c in xhs:
    if c["name"] not in by_name or c.get("domain") == ".xiaohongshu.com":
        by_name[c["name"]] = c["value"]
cookie_str = "; ".join(f"{k}={v}" for k, v in by_name.items())
print("cookies loaded:", len(by_name), "chars:", len(cookie_str))
assert "a1=" in cookie_str and "web_session=" in cookie_str, "missing a1/web_session"

auth = XHSPcAuth.from_cookie(cookie_str)
print("bootstrap OK, user_id:", auth.user_id)

api = XHS_Apis(auth)
success, msg, res = api.search_note("10分钟快手菜", page=1)
print("search success:", success, "msg:", msg)
if res:
    items = ((res.get("data") or {}).get("items") or [])
    print("items returned:", len(items))
    for it in items[:5]:
        note = it.get("note_card") or {}
        user = note.get("user") or {}
        print("-", note.get("display_title"), "|", user.get("nickname"),
              "| likes:", (note.get("interact_info") or {}).get("liked_count"))
