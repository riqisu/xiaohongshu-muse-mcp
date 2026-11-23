# MCP server — Go MCP (`xpzouying/xiaohongshu-mcp` v2.7.4)

Upstream: https://github.com/xpzouying/xiaohongshu-mcp (Apache-2.0).
Binaries are downloaded by `setup.sh` from the v2.7.4 release and
SHA-256 verified; they are not committed here.

## What it is for in this repo

- **Login** (`get_login_qrcode`, headed login tool) and
  `check_login_status`. That is the reliable part.
- **Not for search.** `search_feeds` times out at 60 s every time
  (fresh browser per call + slow proxy). Use
  `spider/rednote_api.py search` instead.

## Run it

```bash
mcp/bin/start-all.sh   # relay -> Xvfb :99 -> MCP :18060 (idempotent)
mcp/bin/status.sh      # processes + ports + cookie count + login status
mcp/bin/stop-all.sh    # stop everything (cookies.json is kept)
```

Server: `http://127.0.0.1:18060/mcp`, Streamable HTTP, no auth.
18 tools; only these 9 read-only tools are allowed in `bin/client.py`:
`check_login_status`, `get_feed_detail`, `get_login_qrcode`,
`get_my_profile`, `get_unread_count`, `list_feeds`,
`list_notifications`, `search_feeds`, `user_profile`.
Publish / comment / like / favourite / `delete_cookies` are not
allowed in this repo's scope.

## Scripts (`mcp/bin/`)

| Script | Use |
|---|---|
| `start-all.sh` | Bring the whole stack up, skipping what is already running. |
| `status.sh` | Health check + login status (~20 s). |
| `stop-all.sh` | Stop server, login tool, relay, Xvfb. |
| `get-qr.py` | Fresh MCP QR on demand (~10 s, 4 min validity). **Enlarge + add a white border before sending the PNG to the user** — the raw image is 128×128 with no quiet zone and phones cannot scan it. |
| `login-qr.sh` | Headed login-tool path (the one that logged in first): retry loop, Xvfb screenshot + crop. Verify the crop visually before sending. |
| `submit-sms.py <code>` | SMS code into the headed Chrome via CDP, ~5 s. Only if a scan lands on the SMS dialog; send the code immediately. |
| `client.py` | MCP client (`list-tools`, `call-tool`). `XHS_MCP_TIMEOUT` env (default 120 s; QR needs 300). |
| `relay.py` | Localhost CONNECT relay for the bundled Chrome. Only needed if the machine reaches the internet through an egress proxy — set `XHS_UPSTREAM_PROXY=<host:port>`. Binds only 127.0.0.1:8888. |
| `setup-python.sh` | Reinstall pip helpers + Xvfb after a restart wipes them. |
| `xhs-env.sh` | Shared env (`XHS_PROXY`, `DISPLAY`, unset VM proxy vars). |

## Notes

- The server fakes a Windows fingerprint (`platform=windows`, fixed
  seed) — the QR shows a Windows device. That is upstream
  anti-detection behaviour.
- `check_login_status` is flaky on the first call after a login;
  retry once before concluding.
- `cookies.json` lives in `mcp/` after a login. It is local-only,
  git-ignored, and holds both a guest `.xiaohongshu.com` session and
  the real `.rednote.com` session — see the repo README for why that
  distinction matters.
- First run downloads the bundled headless browser (~150–190 MB).
