#!/usr/bin/env bash
# Health check for the Xiaohongshu stack + login state.
# Usage: bin/status.sh
# Prints relay / xvfb / mcp process state, cookies count, and the MCP
# check_login_status result (takes ~20 s; the MCP server must be up).
set -u
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1
. ./bin/xhs-env.sh

pgrep -f "[r]elay.py" >/dev/null && echo "relay: up" || echo "relay: DOWN"
pgrep -f "[X]vfb :99" >/dev/null && echo "xvfb: up (:99)" || echo "xvfb: DOWN"
if curl -s -o /dev/null --max-time 5 http://127.0.0.1:18060/mcp; then echo "mcp: up (:18060)"; else echo "mcp: DOWN"; fi
python3 -c "
import json
d = json.load(open('cookies.json'))
print('cookies:', len(d.get('cookies', [])), 'saved_at:', d.get('saved_at'))
"
echo '{}' > /tmp/args-empty.json
python3 bin/client.py call-tool --name check_login_status --arguments-file /tmp/args-empty.json 2>&1 | head -c 400; echo
