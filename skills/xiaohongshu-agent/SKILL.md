---
name: xiaohongshu-agent
description: Log in to Xiaohongshu (小红书 / rednote) and search, read notes, and read the user's own collections from a Muse chat, using the xiaohongshu-muse-mcp repo. Use when the user asks to log in to Xiaohongshu, search Xiaohongshu, read a shared Xiaohongshu post, or organise their Xiaohongshu collections. Do not use for publishing live, commenting, liking, or favouriting.
---

# Xiaohongshu agent

Repo: `xiaohongshu-muse-mcp` (clone it first if it is not already in the
workspace; run `./setup.sh` once — see the repo README).

## Scope (hard limits)

- Search / read only. Reading a shared post, keyword search, reading
  your own collections, and note detail are in scope.
- Draft publishing is a future step and needs a separate explicit
  approval. Publishing live, commenting, liking, favouriting, and
  `delete_cookies` are out of scope — never do them.
- Never print, store, or commit a cookie value, phone number, SMS code,
  password, `xsec_token` value, or QR session ID. Print only counts,
  titles, and API result codes. `cookies.json` is local-only.

## The one thing to remember

Login lands on **rednote.com**. The `.xiaohongshu.com` cookies are a
**guest** session. The working route is:

> **rednote cookies → `https://webapi.rednote.com` → Spider_XHS local
> signing (`spider/rednote_api.py`)**

Do NOT use MCP `search_feeds` for search — it times out at 60 s every
time (fresh browser per call). Do NOT send rednote cookie values to
`edith.xiaohongshu.com` — that returns `-100 登录已过期`.

## Setup (once)

```bash
git clone <repo-url> xiaohongshu-muse-mcp && cd xiaohongshu-muse-mcp
./setup.sh            # vendor clones, MCP binaries (SHA-256 verified), Spider venv
mcp/bin/start-all.sh  # relay -> Xvfb :99 -> MCP :18060; idempotent, skips what is up
```

If the machine needs an egress proxy, set `XHS_UPSTREAM_PROXY=<host:port>`
before `start-all.sh` (the relay forwards Chrome's CONNECT through it)
and export `HTTP_PROXY`/`HTTPS_PROXY` for `setup.sh`. If no proxy is
needed, skip the relay.

## Login flow (QR → phone verification → verify real login)

0. **Run the script, do not hand-step the login.** Start
   `mcp/bin/login-auto.py` in the background — it owns QR generation,
   enlarge + white border, unique sendable filename, polling
   `check_login_status`, and auto-refresh on expiry, and prints
   `QR:<path>`, `LOGIN-OK` or `LOGIN-FAILED`. The agent only sends the
   QR from `mcp/tests/login-auto-state.json` (`pngPath`) and reports the
   result. Manual generation / polling is the fallback, not the default.
1. Check state first: `mcp/bin/status.sh` and MCP `check_login_status`.
   If already ✅, skip to verification step 5.
2. **Only generate a QR when the user says they are ready to scan now.**
   Codes live 180 s (Spider) / 4 min (MCP). Generate with
   `mcp/bin/get-qr.py` (dynamic QR, ~10 s). Do not generate a second
   QR while one is live — it invalidates the first.
3. **Before sending the QR, enlarge it and add a white border.**
   The MCP returns a 128×128 image with no quiet zone; phones cannot
   scan it as-is (and a plain image decoder cannot read it either —
   add a ~20 px white border first, then decode to verify it reads as
   a `https://www.xiaohongshu.com/mobile/login?...` URL). Send the
   enlarged file with a unique filename and the expiry time in text.
   The user must scan **inside the Xiaohongshu app** (scan / 扫一扫)
   and tap confirm immediately. System camera / WeChat scan does not
   reach the login confirmation. One account cannot stay logged in on
   multiple web sessions — use the account the user intends, and do
   not log that account in elsewhere at the same time.
4. If the app asks for an SMS code: it goes to the phone number bound
   to the account. Ask the user to send the code immediately (5 min
   validity; 3 failed submits rate-limit the account). Submit it in
   ~5 s with `mcp/bin/submit-sms.py <code>` (CDP into the headed
   Chrome). Never re-submit an expired code. If the code path fails,
   the headed-login alternative is `mcp/bin/login-qr.sh`.
5. **Verify a real login — both must hold:**
   - MCP `check_login_status` → ✅. Retry once: the first check after
     a login is flaky and can say ❌.
   - `spider/rednote_api.py me` → `guest: false` for the logged-in
     account. Cookie count alone proves nothing — a guest session
     also saves 30+ cookies.
   - Then `./scripts/verify.sh` (search + first collect page).

## Using it after login

```bash
# search (generic example query; use the user's own keywords)
vendor/Spider_XHS/.venv/bin/python spider/rednote_api.py search "<keywords>"
# collections, first page (or: collect --all)
vendor/Spider_XHS/.venv/bin/python spider/rednote_api.py collect
# note detail (note_id + xsec_token come from a search result or a share link)
vendor/Spider_XHS/.venv/bin/python spider/rednote_api.py note <note_id> <xsec_token>
```

- **Shared post (QR image / link from the user):** decode the QR in
  the image (OpenCV `QRCodeDetector`, add a white border first if it
  does not decode), resolve the short link to `note_id` + `xsec_token`,
  call `note` — return the full text + all images. Videos: title /
  intro / comments only, no transcription.
- **Comments:** fetchable with the Spider comment APIs; report them
  as written, including nested replies.
- **Summaries:** report only what the post says. No added commentary
  or judgement. If something needs checking, check a source first
  (e.g. a news channel for a news post) — never judge from memory.
- **Links:** every result must carry its original post link so the
  reader can open the source directly:
  `https://www.xiaohongshu.com/explore/<note_id>?xsec_token=<token>&xsec_source=pc_search`
  (omit the token param when there is none). `rednote_api.py` already
  prints this link for `search`, `collect`, and `note` — include it in
  the reply as well, don't strip it.

## Troubleshooting

| Symptom | Fix |
|---|---|
| QR won't scan | Enlarge + white border; scan inside the app. |
| QR expired / no scan detected | Generate only when the user is ready; scan + confirm immediately. |
| SMS expired / "too many errors" | Send the code at once; CDP submit (~5 s); never re-submit an expired code; use the bound number. |
| SMS submitted but the code expired anyway | A stale Chrome from a previous login round can steal the submit (wrong DevTools port). Run `mcp/bin/cleanup-login.sh` after every login round; `submit-sms.py` now picks the newest Chrome and checks the SMS dialog is actually open before typing. |
| `check_login_status` ❌ right after login | Retry once. |
| Spider search `-104` | Guest session on xiaohongshu.com — use `rednote_api.py`. |
| Spider `-100` | Rednote cookies sent to a xiaohongshu.com host — wrong host, use webapi.rednote.com. |
| MCP `search_feeds` timeout | Expected. Use `rednote_api.py search`. |
| Collect `-1` | Empty `xsec_token` — take it from `user/me` (the script does this). |
| Session dropped later | Same account logged in elsewhere kicked it out — log in again. |

Full session notes, including every failure and root cause, are in
the repo at `docs/session-summary.md`.
