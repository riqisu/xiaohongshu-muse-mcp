#!/usr/bin/env python3
"""Generate a fresh Xiaohongshu login QR code on demand (dynamic QR).

Calls the MCP server's get_login_qrcode tool (base64 QR image) and saves
it as a PNG. The QR is valid for ~4 minutes from generation; the server
waits that long for the scan, then the session ends. Scan with the
Xiaohongshu app and tap confirm in the app immediately.

Usage:
  python3 bin/get-qr.py
Prints the PNG path and the scan deadline. The latest QR is always also
copied to tests/login-qrcode-latest.png.

Requires: the stack up (bin/start-all.sh). The QR call can take ~35 s
(the server launches its browser), so this client uses a 300 s timeout.
Does NOT touch cookies.json and does NOT log the user out: an unscanned
QR simply expires.
"""
import base64
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["XHS_MCP_TIMEOUT"] = "300"

from client import call_rpc  # noqa: E402

HERE = Path(__file__).resolve().parent
TESTS = HERE.parent / "tests"


def main():
    result = call_rpc("tools/call", {"name": "get_login_qrcode", "arguments": {}})
    if result.get("isError"):
        print("error: get_login_qrcode failed:", result, file=sys.stderr)
        return 1
    png_bytes = None
    text_parts = []
    for item in result.get("content", []):
        if item.get("type") == "image" and item.get("data"):
            png_bytes = base64.b64decode(item["data"])
        elif item.get("type") == "text" and item.get("text"):
            text_parts.append(item["text"])
            m = re.search(r"data:image/png;base64,([A-Za-z0-9+/=]+)", item["text"])
            if m:
                png_bytes = base64.b64decode(m.group(1))
    text = "\n".join(text_parts)
    if png_bytes is None:
        print("error: no QR image in MCP response:", text[:500], file=sys.stderr)
        return 1
    TESTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = TESTS / f"login-qrcode-mcp-{stamp}.png"
    path.write_bytes(png_bytes)
    latest = TESTS / "login-qrcode-latest.png"
    latest.write_bytes(png_bytes)
    print(f"qr: {path}")
    print(f"latest: {latest}")
    if text:
        print("server says:", text[:300])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
