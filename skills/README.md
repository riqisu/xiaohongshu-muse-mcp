# Skills — upstream `xiaohongshu-skills` (Chrome-extension bridge)

Upstream: https://github.com/autoclaw-cc/xiaohongshu-skills
(cloned by `setup.sh` into `vendor/xiaohongshu-skills` at a pinned
commit; its own licence applies). Nothing from it is vendored here.

It is a SKILL.md-format skill set (OpenClaw / Claude Code) with five
sub-skills: `xhs-auth` (login check / QR / phone code), `xhs-explore`
(keyword search, note detail, user home, recommendations),
`xhs-interact` (comment / like / favourite), `xhs-publish`
(publishing), `xhs-content-ops` (combined operations). It works via a
Chrome-extension bridge: `extension/` + `scripts/bridge_server.py` +
`scripts/cli.py`, with subcommands like `check-login`,
`get-qrcode`, `wait-login`, `phone-login`, `send-code`,
`verify-code`, `search-feeds`, `get-feed-detail`, `user-profile`,
`list-feeds`. Needs Python 3.11+, `uv`, Chrome + the extension
installed.

**Status in this repo: not installed, not configured.** It is the
fallback route if the MCP + Spider routes ever stop working (install
the extension, run `bridge_server.py`, use `cli.py search-feeds`).
Its `xhs-publish` / `xhs-interact` sub-skills are out of this repo's
search/read-only scope — do not use them without a separate explicit
decision.

The skill this repo actually ships for Muse is
`skills/xiaohongshu-agent/SKILL.md` — copy that one into Muse.
