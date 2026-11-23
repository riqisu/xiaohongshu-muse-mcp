#!/usr/bin/env python3
"""Xiaohongshu MCP client (local, no-auth, search/read-only).

Server: xpzouying/xiaohongshu-mcp v2.7.4, local binary
  ~/workspace/custom-connectors/custom.xiaohongshu/bin/xiaohongshu-mcp-linux-amd64
  running at http://127.0.0.1:18060/mcp (Streamable HTTP, no auth, no API key).
Login is by QR code scan in the Xiaohongshu app; the session cookie is
stored locally in ~/workspace/custom-connectors/custom.xiaohongshu/cookies.json.
No password, token or cookie goes in this file, a command argument, an
environment variable or a log.

Verified 2026-11-23 in this sandbox:
- Server starts, registers 18 MCP tools, initialize returns
  serverInfo xiaohongshu-mcp 2.0.0, protocol 2025-03-26.
- tools/list works with a single POST, no initialize handshake needed
  (same stateless pattern as the Sell The News client).
- First run downloads the bundled headless browser (~150-190 MB) once
  to ~/.cache/xiaohongshu-mcp/browser/.

Usage:
  python3 bin/client.py list-tools [--cursor <cursor>]
  python3 bin/client.py call-tool --name <tool> --arguments-file <json>
Only the 9 read-only tools below are allowed. Publish / comment / like /
favorite / reply / delete_cookies are NOT in ALLOWED_TOOLS and need a
separate explicit approval plus a code change before anyone runs them.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests

ENDPOINT = "http://127.0.0.1:18060/mcp"
PROTOCOL = "2025-03-26"
# Per-request timeout in seconds; the QR call needs ~35 s+ (browser launch),
# so get-qr.py sets XHS_MCP_TIMEOUT=300. Default 120 s.
TIMEOUT = int(os.environ.get("XHS_MCP_TIMEOUT", "120"))
ALLOWED_TOOLS = {
    "check_login_status",
    "get_feed_detail",
    "get_login_qrcode",
    "get_my_profile",
    "get_unread_count",
    "list_feeds",
    "list_notifications",
    "search_feeds",
    "user_profile",
}
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": PROTOCOL,
    "User-Agent": "muse-custom-connector/1",
}


class McpError(RuntimeError):
    pass


def call_rpc(method, params, request_id=1):
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    try:
        resp = requests.post(
            ENDPOINT, json=payload, headers=HEADERS, timeout=TIMEOUT, allow_redirects=False
        )
    except requests.RequestException as exc:
        raise McpError(f"MCP request did not complete: {exc}") from None
    if resp.status_code in (301, 302, 303, 307, 308):
        raise McpError("MCP endpoint redirected; verify the endpoint before continuing")
    if resp.status_code != 200:
        raise McpError(f"MCP returned HTTP {resp.status_code}; the operation was not replayed")
    content_type = resp.headers.get("Content-Type", "")
    if "application/json" in content_type:
        message = resp.json()
    elif "text/event-stream" in content_type:
        message = None
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                message = json.loads(line[5:].lstrip(" "))
                break
        if message is None:
            raise McpError("MCP event stream carried no data message")
    else:
        raise McpError(f"MCP returned unsupported content type: {content_type}")
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        raise McpError("MCP returned an invalid JSON-RPC message")
    if message.get("id") != request_id:
        raise McpError("MCP returned the wrong request ID")
    if "error" in message:
        raise McpError(f"MCP returned a JSON-RPC error: {message['error']}")
    result = message.get("result")
    if not isinstance(result, dict):
        raise McpError("MCP returned no result object")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    listing = subparsers.add_parser("list-tools")
    listing.add_argument("--cursor")
    calling = subparsers.add_parser("call-tool")
    calling.add_argument("--name", required=True)
    calling.add_argument("--arguments-file", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "call-tool":
        if args.name not in ALLOWED_TOOLS:
            parser.error("Inspect this operation's schema and add its exact name to ALLOWED_TOOLS")
        arguments = json.loads(args.arguments_file.read_bytes())
        if not isinstance(arguments, dict):
            parser.error("arguments must be a JSON object")
        result = call_rpc("tools/call", {"name": args.name, "arguments": arguments})
    else:
        result = call_rpc(
            "tools/list", {"cursor": args.cursor} if args.cursor else {}
        )
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result.get("isError") else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (McpError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
