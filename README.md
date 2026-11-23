# xiaohongshu-muse-mcp

Give a Muse agent end-to-end Xiaohongshu (小红书 / rednote) access:
**QR login → phone verification → search, read notes, and read your own
collections — with local signing, no browser search.**

Copy this repo, run one setup script, log in once by scanning a QR code
in the Xiaohongshu app, and the agent can search and read from then on.

> Scope of this repo: **search / read only**. Publishing as a draft is
> described as a future step and is off by default; publishing live,
> commenting, liking, and favouriting are out of scope. Nothing here
> sends, stores, or prints passwords, phone numbers, or cookies.
> `cookies.json` is local-only and git-ignored — never commit it.

## Why this repo exists

The obvious route does not work. Verified live (2026-11-23):

1. The Go MCP server (`xpzouying/xiaohongshu-mcp` v2.7.4) logs in fine,
   but its `search_feeds` times out every time (60 s server deadline):
   every tool call cold-starts a fresh browser and reloads the heavy
   search page through a slow proxy.
2. Login lands on **rednote.com**, not xiaohongshu.com. The saved
   `.xiaohongshu.com` cookies are only a **guest** session
   (`user/me` → `guest: true`, search → `-104 没有权限访问`).
   The real session lives in the `.rednote.com` cookies.
3. The fix: send the **rednote cookies to the rednote API host**,
   `https://webapi.rednote.com`, using Spider_XHS local signing
   (no browser). There `user/me` returns `guest: false`, v2 search
   works, the collect page works, and note detail works.
   Sending rednote cookie *values* to `edith.xiaohongshu.com` fails
   with `-100 登录已过期` — cookies are domain-scoped.

## Layout

| Path | What it is |
|---|---|
| `setup.sh` | One-command setup: clones upstreams at pinned commits, downloads the MCP binaries (SHA-256 verified), builds the Spider venv. |
| `mcp/bin/` | Our MCP helper scripts: `start-all.sh`, `status.sh`, `stop-all.sh`, `get-qr.py` (dynamic QR), `login-qr.sh` (headed login tool), `submit-sms.py` (fast SMS submit via CDP), `client.py` (MCP client), `relay.py` (optional localhost CONNECT relay). Binaries are downloaded by `setup.sh`, not committed. |
| `mcp/README.md` | MCP server details, tools, and troubleshooting. |
| `spider/rednote_api.py` | **The working route.** Search / read notes / read collections via `webapi.rednote.com` + local signing. `me`, `search`, `collect`, `note` subcommands. |
| `spider/qr_login.py`, `spider/sms_login.py` | Spider QR / SMS login drivers (alternative login path). |
| `spider/test_search.py` | Diagnostic: the old xiaohongshu.com route (expected `-104`). |
| `skills/` | Notes on the upstream `xiaohongshu-skills` repo (Chrome-extension bridge route — not installed by default). |
| `skills/xiaohongshu-agent/SKILL.md` | **Copy this into Muse** (`~/workspace/custom-skills/xiaohongshu-agent/SKILL.md`) so the agent knows this whole flow. |
| `docs/session-summary.md` | Full session notes: timeline, every failure and its root cause, pitfalls. |
| `docs/muse-setup.md` | Wiring it into Muse: skill install + MCP server config. |
| `vendor/` | Created by `setup.sh` (upstream clones — not committed). |

Upstream projects (their own licences apply):
`xpzouying/xiaohongshu-mcp` v2.7.4 (Apache-2.0),
`cv-cat/Spider_XHS` @ `23dab80`,
`autoclaw-cc/xiaohongshu-skills` @ `b043748`.

## End-to-end: copy, set up, log in, verify

```bash
git clone https://github.com/<you>/xiaohongshu-muse-mcp.git
cd xiaohongshu-muse-mcp
./setup.sh            # clones vendor/, downloads MCP binaries, builds venv
mcp/bin/start-all.sh  # relay -> Xvfb :99 -> MCP server :18060 (idempotent)
```

Then, in your Muse chat, say:

> 用这个 repo 的流程帮我登录小红书。

The agent will:

1. Check the stack and current login state (`mcp/bin/status.sh`).
2. Generate a fresh QR code (`mcp/bin/get-qr.py`, ~10 s, 4 min validity).
3. **Enlarge it and add a white border before sending it to you.**
   The MCP returns a 128×128 QR with no quiet zone — phones cannot
   scan it as-is. This is the single most common failure.
4. You scan it **inside the Xiaohongshu app** (scan / 扫一扫) and tap
   confirm immediately. Scanning with the system camera or WeChat
   does not reach the login confirmation.
5. If the app asks for an SMS code: it goes to the phone number bound
   to the account. Send the code to the agent right away (5 min
   validity, 3 failed submits rate-limit the account) — the agent
   submits it in ~5 s via `mcp/bin/submit-sms.py`.
6. Verify the login is *real* — both of these must hold:
   - MCP `check_login_status` → ✅ (retry once; the first check is
     flaky and can say ❌ right after a successful login).
   - Spider `user/me` on webapi → `guest: false`.
   Cookie count alone proves nothing: a guest session also saves
   30+ cookies.

Verify everything works:

```bash
./scripts/verify.sh
# runs: rednote_api.py me, search for a generic query, collect (first page)
```

Or directly:

```bash
vendor/Spider_XHS/.venv/bin/python spider/rednote_api.py me
vendor/Spider_XHS/.venv/bin/python spider/rednote_api.py search "10分钟快手菜"
vendor/Spider_XHS/.venv/bin/python spider/rednote_api.py collect
vendor/Spider_XHS/.venv/bin/python spider/rednote_api.py note <note_id> <xsec_token>
```

`rednote_api.py` reads the MCP login's `cookies.json`
(`XHS_COOKIES_JSON` env var overrides the path; default
`mcp/cookies.json`).

## What the agent can do after login

- **Read a shared post:** give it a share image / QR code / link and it
  decodes the QR, resolves the short link to `note_id` + `xsec_token`,
  and returns the full text + all images. Videos: title/intro/comments
  only, no transcription.
- **Search:** keyword search, with titles, authors, like counts, note IDs.
- **Collections:** list your own collected notes (paged; `--all` for all).
- **Summaries:** report only what the post says. No added commentary
  or judgement — if something needs checking, check a source first.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| QR won't scan / "can't jump" | 128×128 with no white border. Enlarge + add a white border (see `get-qr.py` output handling in the skill). Scan inside the Xiaohongshu app, not the system camera. |
| QR expired, no scan detected | Codes live 180 s (Spider) / 4 min (MCP). Generate only when the user is ready to scan *now*, scan + confirm immediately. |
| SMS code expired / "too many errors" | Codes live 5 min; 3 failed submits rate-limit the account. Submit via CDP (`submit-sms.py`, ~5 s), never re-submit an expired code. Use the account's bound number, not an unbound one. |
| `check_login_status` says ❌ right after login | Known flaky first check — retry once before concluding. |
| Spider search `-104` | Guest session on xiaohongshu.com. Use `rednote_api.py` (webapi.rednote.com + rednote cookies). |
| Spider `-100 登录已过期` | Rednote cookie values sent to a xiaohongshu.com host. Wrong host — use webapi.rednote.com. |
| MCP `search_feeds` 60 s timeout | By design (fresh browser per call). Don't retry it — use `rednote_api.py search`. |
| Collect page `-1 薯队长遇到一些小麻烦` | Empty `xsec_token`. Take it from `user/me` first (the script does this). |
| Login kicked out later | One account can't stay logged in on multiple web sessions. Don't log the same account in elsewhere. |

Full notes: [`docs/session-summary.md`](docs/session-summary.md).

## Security notes

- Never commit `cookies.json`, `spider-cookies.txt`, QR images,
  `*-result.json`, or anything under `vendor/` — see `.gitignore`.
- Never put a cookie value, phone number, SMS code, or password in a
  file, a log, or a chat message that gets shared. The scripts only
  ever print counts, titles, and API result codes.
- The MCP server fakes a Windows fingerprint (`platform=windows`) —
  the QR will show a Windows device. That is the upstream server's
  anti-detection behaviour, not a different machine.
- This repo automates a third-party site's web login. Use your own
  account, respect the site's rules and rate limits, and keep the
  scope to reading your own content.
