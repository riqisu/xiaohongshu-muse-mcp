# Session summary — how this route was found

Verified live 2026-11-23. All account identifiers, phone numbers,
session IDs, and cookie values have been removed from this copy;
the flow and the failure analysis are what matter.

## Goal

Given a Xiaohongshu share (QR code / link), access and summarise the
post — recipes, AI articles, interesting videos. Plus, later: publish
as **draft only** (never live) and organise the user's collections so
previously seen content is findable fast. Scope: search / read only.

## Core rule

**QR login → pass phone verification → then use the MCP and Spider_XHS
for search and access; do not search with the built-in browser.**

## What was tried, in order

### 1. Go MCP (`xpzouying/xiaohongshu-mcp` v2.7.4)

- Server starts, `tools/list` works (18 tools, 9 read-only allowed).
- Login works: QR code, scan in the app, confirm. Twice verified
  `check_login_status` ✅. The server fakes a Windows fingerprint
  (`platform=windows`, fixed seed), so the QR shows a Windows device.
- **Search does not work:** `search_feeds` times out at 60 s, 7/7
  attempts. Root cause (upstream source read): every tool call opens
  a **fresh browser** (`newBrowser()` per operation, discarded after),
  so each search pays a cold Chrome launch + full search-page load
  through a slow proxy. The 60 s deadline is hardcoded
  (`search.go`, `page.Timeout(60 * time.Second)`); there is no flag
  for it, so lengthening it needs a source rebuild + Go toolchain.
  The search API request does fire (relay log shows the connections
  growing) — it just never becomes "ready" in time.
- The headed login tool needs a real display: headless fails with
  `Missing X server or $DISPLAY`. Fix: Xvfb `:99` + screenshots.
- MCP `check_login_status` is flaky on the first call after a login
  (can say ❌, then ✅ on retry). Always retry once.
- The MCP QR image is only 128×128 with no white border: phones
  cannot scan it as-is, and a plain decoder cannot read it either.
  **Enlarge it and add a white border before sending**; verify it
  decodes to a `.../mobile/login?...` URL before sending. Scan inside
  the Xiaohongshu app — system camera / WeChat scan does not reach
  the login confirmation.
- QR codes live 180 s (Spider) / 4 min (MCP). Generate only when the
  user is ready to scan *now*; scan + confirm immediately. Do not
  generate a second QR while one is live.
- SMS codes live 5 min; 3 failed submits rate-limit the account.
  Submit via CDP (`submit-sms.py`, ~5 s), never re-submit an expired
  code. Use the phone number bound to the account.
- One account cannot stay logged in on multiple web sessions — a
  login elsewhere kicks the session out. The session can also drop
  on its own; re-login is the fix.

### 2. Spider_XHS local signing (`cv-cat/Spider_XHS`)

- Local signing works and is fast (~3 s/call, no browser):
  `user/me` and search suggestions succeed.
- **But with the MCP cookies it is a guest session:** `user/me`
  returns `guest: true`, and search (v1, v2, onebox, user search)
  all return code `-104 没有权限访问`.
- Cookie pitfall: `cookies.json` holds the same names under both
  `.xiaohongshu.com` and `.rednote.com` with **different values**.
  Merging them into one dict (last wins) sends the wrong values and
  gives "登录已过期". Always filter by domain.
- Spider QR re-login: two confirmed scans both failed at the final
  step ("登录异常") — the server blocks the local-signing login at
  that step, most likely demanding phone verification, which that
  flow does not complete. SMS login to an unbound number fails
  (`-13005`, no SMS sent) — use the bound number.
- `requirements.txt` omits `cryptography` and `Pillow`, both needed
  by the login flow — install them (setup.sh does).

### 3. The breakthrough: rednote cookies → webapi.rednote.com

- Login lands on rednote.com. The real session is the
  `.rednote.com` cookie set (it carries an `id_token` and a different
  `web_session`); the `.xiaohongshu.com` set is the pre-login guest
  session.
- Sending rednote cookie *values* to `edith.xiaohongshu.com` still
  fails (`-100 登录已过期`) — cookies are domain-scoped.
- Sending the rednote cookies to **`https://webapi.rednote.com`**
  works: `user/me` → `guest: false`; v2 search → real results;
  collect page → real results (with the `xsec_token` from `user/me`;
  an empty token returns code `-1`); note detail → full content +
  images. `www.rednote.com/api/...` only returns the frontend page;
  `edith.rednote.com` does not exist.
- Two Spider quirks, both worked around in `spider/rednote_api.py`:
  1. `XHSPcAuth.from_cookie()` immediately calls `bootstrap()`
     against edith, which rejects rednote cookies. Patch bootstrap
     to a no-op for construction, then set the real `user_id` from
     a webapi `user/me` call.
  2. The collect page needs the `xsec_token` from `user/me`.

## What already works without a login

Reading a specific shared post needs no real login: decode the QR
in the share image → resolve the short link to `note_id` +
`xsec_token` → Spider `get_note_info` with guest cookies returns
the full note (title, body, author, counts, image URLs). Comments
work the same way (including nested replies and images in comments).
Videos: title / intro / comments only, no transcription.

## Standing rules learned

- Summarise a post by reporting only what it says — no added
  commentary or judgement. If something needs checking, check a
  source first; never judge from memory.
- When given a share image, fetch the full text + all images.
  Videos are not needed.
- Verify a login with `guest: false`, not with cookie count.
  MCP ✅ alone is not enough.
- Never repeat a failed step the same way: if a QR expired, generate
  a fresh one when the user is ready; if MCP search times out, switch
  to the Spider route instead of retrying.
