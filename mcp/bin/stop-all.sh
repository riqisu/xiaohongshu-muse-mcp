#!/usr/bin/env bash
# Stop the Xiaohongshu stack: MCP server, headed login tool, relay, Xvfb.
# Does NOT delete cookies.json — the login survives a stop/start.
set -u
pkill -f "[x]iaohongshu-mcp-linux-amd64" 2>/dev/null
pkill -f "[x]iaohongshu-login-linux-amd64" 2>/dev/null
pkill -f "[r]elay.py" 2>/dev/null
pkill -f "[X]vfb :99" 2>/dev/null
sleep 1
echo "stopped: mcp, login tool, relay, xvfb (cookies.json kept)"
