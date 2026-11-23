#!/usr/bin/env bash
# Shared environment for the Xiaohongshu connector scripts.
# Source it from the other scripts in bin/ — it only affects that script's shell.
# - XHS_DIR: this connector's directory (cookies.json, bin/, tests/)
# - XHS_PROXY: the localhost CONNECT relay (relay.py) the browsers use.
#   The VM's egress proxy vars must be UNSET for the Go binaries, or rod
#   fails with ERR_NO_SUPPORTED_PROXIES / ERR_TUNNEL_CONNECTION_FAILED.
# - DISPLAY :99 is the Xvfb virtual screen the headed login tool needs.
export XHS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export XHS_PROXY="http://127.0.0.1:8888"
export DISPLAY=":99"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
