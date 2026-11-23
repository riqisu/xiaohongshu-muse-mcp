#!/usr/bin/env bash
# Reinstall the Python helpers after a VM restart wipes pip packages
# (mss, python-xlib, websocket-client, pillow, requests).
# Also reinstalls Xvfb if the system package is gone.
# Run: bin/setup-python.sh
set -u
if ! command -v Xvfb >/dev/null 2>&1; then
  echo "installing xvfb..."
  apt-get install -y xvfb
fi
# If your network needs an egress proxy, export HTTP_PROXY/HTTPS_PROXY
# before running this script; nothing is hardcoded here.
pip install --break-system-packages mss python-xlib websocket-client pillow requests
python3 -c "import mss, PIL, websocket, Xlib, requests; print('python helpers ok')"
