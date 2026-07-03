#!/bin/bash
# Bump BusTrain asset version so Cloudflare edge + browser caches are bypassed.
# Usage: scripts/release.sh <version-number>
set -euo pipefail
V="${1:?usage: release.sh <version-number>}"
cd "$(dirname "$0")/../web"

sed -i -E "s/(app\.css|app\.js|trips\.js|guide\.js|sw\.js)\?v=[0-9]+/\1?v=$V/g" index.html app.js
sed -i -E "s/app\.css\?v=[0-9]+/app.css?v=$V/g" help.html
sed -i -E "s/bt-shell-v[0-9]+/bt-shell-v$V/; s/(app\.css|app\.js|trips\.js|guide\.js)\?v=[0-9]+/\1?v=$V/g" sw.js

echo "stamped v=$V:"
grep -h "?v=" index.html sw.js | sed 's/^ *//'
grep "SHELL = " sw.js
echo "done — server picks it up immediately (static files read from disk)."
