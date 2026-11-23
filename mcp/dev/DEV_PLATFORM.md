# Xiaohongshu MCP dev platform — simulated environment

Local development / test platform for the Xiaohongshu login + search
automation. The login flow and the search API run against a **mock
Xiaohongshu on 127.0.0.1 only** — no real QR scan, no real SMS code,
no Xiaohongshu risk control, and never the live `cookies.json` or the
running MCP server (`:18060`).

## Run it

```bash
bash mcp/dev/run-dev-test.sh
```

Prints `PASS`/`FAIL` per case, exits 0 only if all pass (~50 s).
Artifacts (screenshots, crops) land in `mcp/dev/runs/<YYYYMMDD-HHMMSS>/`
with unique filenames — never reuse a path (clients cache by path).

Requires: Xvfb `:99` (started by the wrapper if down), the rod
Chrome under `~/.cache/xiaohongshu-mcp/browser/`, the Spider venv
(`vendor/Spider_XHS/.venv`). If deps are missing after a VM restart:

```bash
vendor/Spider_XHS/.venv/bin/pip install -r mcp/dev/requirements-dev.txt
```

## Layout

| file | what it is |
|---|---|
| `mock_xhs.py` | mock server, `127.0.0.1:18100` (login page + mock API + `/state`) |
| `devtest.py` | harness: launches real headed Chrome, runs the REAL `../bin/` scripts, asserts |
| `run-dev-test.sh` | wrapper: Xvfb check → mock server → deps check → `devtest.py` → stop mock |
| `mock-cookies-*.json` | fake cookie files (logged-in / guest / expired). All values fake. |
| `requirements-dev.txt` | pinned Python deps (websocket-client, mss, python-xlib, pillow, opencv, qrcode) |
| `runs/` | per-run artifacts (screenshots, crops) |

## The mock server

- `GET /login?sid=…` — mock login page. Server-driven stages (the
  page polls `/state` every 400 ms and renders): `qr` (login QR) →
  `verify` (security QR) → `sms` (SMS dialog) → `success` / `closed`.
  Chaos knobs as query params: `qr_autoscan`, `verify_autoscan`,
  `verify_ttl` (expiry refreshes back to a fresh login QR),
  `sms_ttl`, `sms_autoclose` (dialog auto-closes), `code`.
- The login QR / security QR are real QR PNGs (`/qr?sid=…&kind=…`)
  positioned so the screenshot crop in `bin/login-qr.sh`
  (`370,400,540,610` on the 1440×1200 Xvfb screen) captures them.
  Calibration: Chrome's UI (tab strip + toolbar + the
  `--host-resolver-rules` infobar) offsets page coords by **+173 px**
  vertically, so the QR sits at page `top:245px` → screen y 418–548.
- `POST /sms-submit` — accepts the expected code only while the
  stage is `sms`; records `sms_submitted` / `sms_submit_count`.
- `GET /state?sid=…` — server-side truth for the harness (stage,
  expected code, what was submitted, verify flag, refresh count).
- `GET /decoy` — a xiaohongshu page with NO SMS dialog (T2).
- Mock API (mimics `webapi.rednote.com`): `GET …/v2/user/me`,
  `POST …/v2/search/notes`, `POST …/v1/feed`, `GET …/v2/note/collect/page`.
  Session class comes from the `web_session` cookie value:
  `mock-web-session` → logged-in, `mock-guest-session` → guest,
  `mock-expired-session`/missing → expired. Error classes mirror the
  real ones: guest search `-104`, wrong-domain/expired note `-100`
  “登录已过期”, mismatched `xsec_token` `300031` “当前笔记暂时无法浏览”,
  empty collect `xsec_token` `-1`. Search/collect items carry the
  per-note `xsec_token` so `rednote_api.py` prints the original post
  link (`https://www.xiaohongshu.com/explore/<id>?xsec_token=…`).

## Tests

- **T1 full mock login round** — QR crop decodes (same steps as
  `login-qr.sh`: mss shot → crop → resize → the real
  `login-auto.py` enlarge+border → OpenCV decode); `submit-sms.py`
  delivers the code; Verify clicks; success page; `cleanup-login.sh`
  leaves no rod Chrome and no stale `/tmp/rod` profiles.
- **T2 stale Chrome skipped** — a decoy Chrome (NEWER `/tmp/rod`
  profile, a xiaohongshu page WITHOUT the SMS dialog) + the current
  mock Chrome; `submit-sms.py` must skip the decoy and use the one
  with the dialog (the 2026-11-23 stale-Chrome bug).
- **T3 dialog closed** — submit after the mock auto-closes the SMS
  dialog → clean exit 1, clear error, no crash, no submit.
- **T4 mock API** — `rednote_api.py` (with `XHS_WEBAPI_BASE` +
  `XHS_COOKIES_JSON` pointed at the mock) for me/search/note/collect,
  including the original post link in search/collect/note output;
  guest/expired cases via direct calls: `-100` / `-104` / `300031`.
- **T5 QR decode** — raw 128×128 (no border) does NOT decode with
  OpenCV; the same QR enlarged to 608×608 + white border (the real
  `login-auto.py` function) DOES decode. Payload is short on purpose:
  the real MCP QR encodes a short login code; a long payload makes a
  denser QR whose 128 px downscale blurs past recovery.

## How the real scripts are used (unchanged)

- `submit-sms.py` and `cleanup-login.sh` run unmodified from
  `../bin/`. Chrome is launched by the harness with
  `--user-data-dir=/tmp/rod/user-data/mock-…` and
  `--remote-debugging-port=…` so `submit-sms.py`'s discovery works.
- `rednote_api.py` takes two env overrides (defaults = live
  behaviour): `XHS_WEBAPI_BASE` (added 2026-11-23, default
  `https://webapi.rednote.com`) and `XHS_COOKIES_JSON`
  (pre-existing, default the live `cookies.json`). The harness
  points both at the mock. `login-qr.sh` is NOT modified — the harness reuses its exact
  screenshot/crop coordinates instead of launching the real login tool.

## Gotchas found while building this (read before debugging)

- **This Chromium build writes no `DevToolsActivePort` file**
  (verified: the file never appears even though `:port` answers).
  `submit-sms.py` discovers Chrome ONLY via that file, so the harness
  writes it itself after launching Chrome (port on line 1, same
  format Chrome uses). The file's mtime is the launch order T2 relies on.
- **Use the rod Chrome** (`~/.cache/xiaohongshu-mcp/browser/*/browser/chrome`,
  Chromium 148). `/opt/meta-chromium/chrome` refuses to start here
  (“Hatch WebGL domain policy is required for browser startup”).
- **Chrome needs `--no-proxy-server`** (and the mock hostname via
  `--host-resolver-rules="MAP mock.xiaohongshu.com 127.0.0.1"`).
  Without it Chrome sends the mock hostname to the egress proxy and
  gets an empty response (`ERR_EMPTY_RESPONSE`). `/etc/hosts` is
  read-only here, and system DNS resolves the mock hostname to a
  sinkhole IP — the resolver rule is required.
- **Proxy vars must STAY set for `rednote_api.py`.** The Spider
  signing path fetches the real ds endpoint
  (`https://as.xiaohongshu.com/api/sec/v1/ds`) on first use; direct
  egress fails TLS (`WRONG_VERSION_NUMBER`), so the ds fetch needs
  the egress proxy. Mock calls to `127.0.0.1` bypass it via `NO_PROXY`.
  Stripping proxy vars in the harness broke T4.
- **Mock `a1` must be 52 hex chars.** The JS signer's `x3` length
  scales with the `a1` length; 52 chars is the unique length passing
  all three tier gates (`0101`→205, `0201`→208, `0301`→200). Shorter
  fake `a1` values make `run_signer` return `None` (“JS mnsv2 签名失败”).
  The mock cookie values are fixed, clearly fake hex — no real credential.
- **`/login` must (re)configure the session.** The harness polls
  `/state` before the page loads, which creates the session with
  DEFAULT chaos knobs; `/login` resets the stage machine from its
  own query params, or a `?sms_autoclose=4` would be silently lost.
- **`threading.RLock`, not `Lock`.** `/sms-submit` holds the lock
  while calling `current_stage()`, which takes it again — a plain
  `Lock` deadlocks the whole server after the first SMS submit.
- **`_send` must not JSON-encode HTML.** The first mock page rendered
  as raw text (literal `\n`, no CSS/JS) because `_send` ran
  `json.dumps` over the HTML string.
- **pkill self-kill trap.** `pkill -f "[/]tmp/rod"` matches ANY
  process whose cmdline contains the literal `/tmp/rod` — including
  your own shell if its command line mentions that path (e.g. a
  `py_compile` of a file under it in the same invocation). Never put
  the literal pattern in the same exec call as the pkill; invoke
  `cleanup-login.sh` by path instead.

## Known issues

- ~~**`submit-sms.py` probe ignores visibility** (fixed 2026-11-23).~~
  It used to find the SMS input by placeholder alone, so a dialog
  hidden but still in the DOM looked "open" and step 3 crashed with
  an unhandled `JSONDecodeError`. The probe now requires a visible
  input (`getBoundingClientRect().width > 0`) and step 3 fails
  cleanly on a non-JSON result. The mock's `closed` stage still
  removes the controls from the DOM (React unmount).
- **First `check_login_status` after an MCP restart is flaky**
  (known, 2026-11-23): it can report ❌ 未登录 once, then ✅ on
  retry. Not a dev-platform issue.

## Adding a new chaos case

1. Add a query knob in `mock_xhs.py` `_cfg()` + the stage machine
   (`current_stage`) and/or the mock API (`api_*`).
2. Add a test function in `devtest.py` (launch Chrome with the knob
   in the `/login` URL, or call the mock API with chosen cookies),
   `record()` a PASS/FAIL line, and call it from `main()`.
3. Run `bash run-dev-test.sh` — it must stay green end to end.
