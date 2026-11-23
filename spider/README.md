# Spider route — local signing via `webapi.rednote.com`

Upstream: https://github.com/cv-cat/Spider_XHS (cloned by `setup.sh`
into `vendor/Spider_XHS` at a pinned commit; its own licence applies).

## The working script

```bash
vendor/Spider_XHS/.venv/bin/python spider/rednote_api.py me
vendor/Spider_XHS/.venv/bin/python spider/rednote_api.py search "<keywords>"
vendor/Spider_XHS/.venv/bin/python spider/rednote_api.py collect [--all]
vendor/Spider_XHS/.venv/bin/python spider/rednote_api.py note <note_id> <xsec_token>
```

`rednote_api.py` reads the MCP login's `cookies.json`
(`XHS_COOKIES_JSON` env var overrides the path), takes only the
`.rednote.com` cookies, signs requests locally with Spider_XHS
(no browser), and talks to `https://webapi.rednote.com`.

Verified: `user/me` → `guest: false`; v2 search → real results;
collect page → real results (needs the `xsec_token` from `user/me`);
note detail → full content + image URLs.

## Other scripts in this folder

| Script | Use |
|---|---|
| `qr_login.py` | Spider QR login driver (saves QR PNG, waits 180 s, writes `spider-cookies.txt` on success — local-only, never commit). Note: confirmed scans can still fail at the final step ("登录异常"); the MCP QR route is the reliable login path. |
| `sms_login.py` | Spider SMS login driver. Set `XHS_PHONE` (digits only) and `XHS_PHONE_ZONE` (default `86`) in the environment. The code is read once from `sms-code.txt` and deleted. |
| `test_search.py` | Diagnostic: the old xiaohongshu.com route. Expected result now is code `-104` (guest session) — it documents why that route is dead. |

## Why webapi.rednote.com

Login lands on rednote.com, so the real session is the
`.rednote.com` cookie set. The `.xiaohongshu.com` set is a guest
session (`guest: true`, search `-104`). Rednote cookie *values*
sent to a xiaohongshu.com host fail with `-100` — cookies are
domain-scoped. The rednote API host is `webapi.rednote.com`
(`www.rednote.com/api/...` returns the frontend page;
`edith.rednote.com` does not exist).

Two quirks are handled inside `rednote_api.py`:
1. `XHSPcAuth.from_cookie()` immediately bootstraps against edith,
   which rejects rednote cookies — bootstrap is patched to a no-op
   for construction, and the real `user_id` is taken from a webapi
   `user/me` call.
2. The collect page needs the `xsec_token` from `user/me`; an empty
   token returns code `-1`.

## Setup notes

`setup.sh` installs the Spider venv plus `cryptography` and `Pillow`
(upstream `requirements.txt` omits them, but login needs them),
`opencv-python-headless` + `qrcode` (QR handling), and Node
`crypto-js` (local signing).
