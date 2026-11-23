#!/usr/bin/env bash
# End-to-end setup for xiaohongshu-muse-mcp.
# Run once after cloning this repo:  ./setup.sh
# Idempotent: already-cloned / already-downloaded pieces are skipped.
# What it does:
#   1. Clones the three upstream projects into vendor/ at pinned commits
#      (their own licences apply; nothing upstream is vendored in this repo).
#   2. Downloads the xiaohongshu-mcp v2.7.4 Linux x64 binaries and verifies
#      their SHA-256 checksums.
#   3. Creates vendor/Spider_XHS/.venv and installs its Python deps
#      (plus cryptography + Pillow, which upstream requirements.txt omits
#      but the QR login flow needs, and opencv + qrcode for QR handling).
#   4. Checks for Xvfb (needed by the headed login tool) and prints
#      the next steps.
# It never asks for, stores, or prints any password, phone number, or cookie.
set -eu
cd "$(dirname "$0")"

MCP_VERSION="v2.7.4"
MCP_SHA="7360e4f1c617acd0d64df807afe64b0c46ca95492ab768c337483cc367f96407"
LOGIN_SHA="2bf99cb365a968015cd096f825c4f838c4cc47a4786252cd9eca145d42b074ff"
SPIDER_COMMIT="23dab80"
SKILLS_COMMIT="b043748"

mkdir -p vendor mcp/bin

clone_pinned() { # repo, dir, commit
  if [ -d "vendor/$2/.git" ]; then
    echo "vendor/$2: already cloned, skipping"
  else
    git clone --depth 1 "https://github.com/$1.git" "vendor/$2"
  fi
  git -C "vendor/$2" fetch --depth 1 origin "$3" 2>/dev/null || true
  git -C "vendor/$2" checkout "$3" 2>/dev/null || echo "vendor/$2: staying on cloned HEAD (pinned commit $3 not fetched -- check network)"
}

clone_pinned "cv-cat/Spider_XHS" "Spider_XHS" "$SPIDER_COMMIT"
clone_pinned "autoclaw-cc/xiaohongshu-skills" "xiaohongshu-skills" "$SKILLS_COMMIT"

download_bin() { # name, sha256
  local name="$1"
  local sha="$2"
  local url="https://github.com/xpzouying/xiaohongshu-mcp/releases/download/${MCP_VERSION}/${name}"
  if [ -x "mcp/bin/${name}" ] && echo "${sha}  mcp/bin/${name}" | sha256sum -c - >/dev/null 2>&1; then
    echo "mcp/bin/${name}: already present, checksum ok"
    return 0
  fi
  echo "downloading ${name} ..."
  curl -fL -o "mcp/bin/${name}" "${url}" || {
    echo "trying ${url}.tar.gz ..."
    curl -fL -o "/tmp/${name}.tar.gz" "${url}.tar.gz"
    tar -xzf "/tmp/${name}.tar.gz" -C mcp/bin "${name}"
  }
  chmod +x "mcp/bin/${name}"
  echo "${sha}  mcp/bin/${name}" | sha256sum -c -
}
download_bin "xiaohongshu-mcp-linux-amd64" "$MCP_SHA"
download_bin "xiaohongshu-login-linux-amd64" "$LOGIN_SHA"

# Spider_XHS Python env
if [ ! -x "vendor/Spider_XHS/.venv/bin/python" ]; then
  python3 -m venv vendor/Spider_XHS/.venv
fi
vendor/Spider_XHS/.venv/bin/pip install -q --upgrade pip
vendor/Spider_XHS/.venv/bin/pip install -q -r vendor/Spider_XHS/requirements.txt
vendor/Spider_XHS/.venv/bin/pip install -q cryptography Pillow opencv-python-headless qrcode requests
# Node crypto-js, needed by Spider_XHS local signing
if [ ! -d "vendor/Spider_XHS/node_modules/crypto-js" ]; then
  (cd vendor/Spider_XHS && npm install --no-audit --no-fund crypto-js 2>/dev/null || npm install --no-audit --no-fund)
fi

if ! command -v Xvfb >/dev/null 2>&1; then
  echo "NOTE: Xvfb is not installed. The headed login tool needs a virtual"
  echo "display. On Debian/Ubuntu: sudo apt-get install -y xvfb"
else
  echo "Xvfb: found"
fi

echo
echo "Setup done. Next steps:"
echo "  1. Start the stack:  mcp/bin/start-all.sh"
echo "  2. In your Muse chat, ask the agent to log in: it will run"
echo "     mcp/bin/get-qr.py, show you a QR code (enlarged, white border),"
echo "     and you scan it inside the Xiaohongshu app and tap confirm."
echo "  3. Verify:  ./scripts/verify.sh"
echo "See README.md for the full end-to-end flow."
