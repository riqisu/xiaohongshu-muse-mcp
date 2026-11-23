# Wiring xiaohongshu-muse-mcp into Muse

Two pieces: the skill (so the agent knows the flow) and, optionally,
the MCP server (so the agent can call the MCP tools directly).

## 1. Install the skill (recommended — this is the main path)

```bash
# from this repo
mkdir -p ~/workspace/custom-skills/xiaohongshu-agent
cp skills/xiaohongshu-agent/SKILL.md ~/workspace/custom-skills/xiaohongshu-agent/SKILL.md
```

Then tell the agent to use it, e.g.:

> 用 xiaohongshu-agent 这个 skill 帮我登录小红书。

The skill tells the agent the whole flow: setup, QR login, SMS,
verification, and the rednote search/collect route. The repo itself
should live somewhere stable, e.g. `~/workspace/xiaohongshu-muse-mcp`,
so the scripts' paths in the skill keep working — or edit the paths
in the skill to point at your checkout.

## 2. MCP server (optional)

The Go MCP server (`xpzouying/xiaohongshu-mcp` v2.7.4) is useful for
login and `check_login_status` / `get_login_qrcode`, but its search
times out — search goes through `spider/rednote_api.py`, not the MCP.
If your Muse setup takes an MCP server config, point it at the local
server after `mcp/bin/start-all.sh` is running:

```json
{
  "mcpServers": {
    "xiaohongshu": {
      "url": "http://127.0.0.1:18060/mcp"
    }
  }
}
```

Only the read-only tools are needed: `check_login_status`,
`get_login_qrcode`, `get_feed_detail`, `get_my_profile`,
`get_unread_count`, `list_feeds`, `list_notifications`,
`search_feeds`, `user_profile`. Do not enable the write tools
(`publish_content`, `post_comment_to_feed`, `like_feed`,
`favorite_feed`, `delete_cookies`, …) unless you have explicitly
decided to — this repo's scope is search/read only.

## 3. Environment variables

| Variable | Use |
|---|---|
| `XHS_COOKIES_JSON` | Path to the MCP login's `cookies.json` (default `mcp/cookies.json`). |
| `XHS_UPSTREAM_PROXY` | `host:port` of an egress proxy, if the machine needs one for the relay (`mcp/bin/relay.py`). Unset = no relay. |
| `XHS_PHONE` / `XHS_PHONE_ZONE` | Phone for the Spider SMS login driver (`spider/sms_login.py`). Digits only; never commit a value. |
| `XHS_MCP_TIMEOUT` | MCP client timeout in seconds (default 120; the QR call needs 300). |

## 4. End-to-end check in a fresh chat

1. "用这个 repo 的流程帮我登录小红书" → scan the QR in the app.
2. `./scripts/verify.sh` → login + search + first collect page all OK.
3. "搜一下 <关键词>" / "读一下这个分享图里的帖子" / "看看我的收藏".
