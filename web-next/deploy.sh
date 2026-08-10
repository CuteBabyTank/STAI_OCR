#!/usr/bin/env bash
#
# Redeploy the frontend, and refuse to finish quietly if it did not work.
#
# The failure this exists to prevent: the server keeps running from an older
# build while the build step replaces the hashed assets on disk. The old
# process then serves old HTML pointing at filenames that were just deleted, so
# every chunk and stylesheet 404s. The page arrives with no CSS - which is what
# turns the phone tab bar into a vertical stack - and React cannot hydrate,
# giving "ChunkLoadError" and "Minified React error #423".
#
# Restarting via `tmux send-keys C-c` is what allowed that: Ctrl-C only reaches
# the FOREGROUND process group of a pane, so a server started with `nohup ... &`
# is untouched by it. Every redeploy then started a second server that died
# instantly on EADDRINUSE while the original kept serving. This script stops the
# server by matching the process, waits for the port to actually release, and
# then verifies that every asset the new HTML references really resolves.
#
# Usage:  ./deploy.sh            (defaults below)
#         PORT=7860 API_BASE=http://127.0.0.1:8000 ./deploy.sh
set -euo pipefail

PORT="${PORT:-7860}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
HOSTNAME_BIND="${HOSTNAME_BIND:-0.0.0.0}"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="${LOG:-$HOME/web.log}"

cd "$APP_DIR"
echo "==> repo: $APP_DIR   port: $PORT   API_BASE: $API_BASE"

echo "==> pulling"
git -C "$APP_DIR/.." pull --ff-only

# --include=dev because next build needs tailwindcss, autoprefixer, postcss and
# typescript, all devDependencies. npm drops those when NODE_ENV=production.
echo "==> installing (exactly the lockfile)"
npm ci --include=dev

echo "==> building"
API_BASE="$API_BASE" npm run build

echo "==> assembling standalone payload"
rm -rf .next/standalone/.next/static .next/standalone/public
cp -r .next/static .next/standalone/.next/
cp -r public .next/standalone/

echo "==> stopping any running server (by process, not by tmux pane)"
pkill -f 'standalone/server.js' || true
for _ in $(seq 1 40); do
  ss -lnt 2>/dev/null | grep -q ":$PORT " || break
  sleep 0.5
done
if ss -lnt 2>/dev/null | grep -q ":$PORT "; then
  echo "!! something is still listening on $PORT after 20s:" >&2
  ss -lntp 2>/dev/null | grep ":$PORT " >&2 || true
  echo "!! kill it by PID and re-run; starting now would serve the OLD build." >&2
  exit 1
fi

echo "==> starting"
PORT="$PORT" HOSTNAME="$HOSTNAME_BIND" nohup node .next/standalone/server.js > "$LOG" 2>&1 &
for _ in $(seq 1 60); do
  curl -fsS -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/" 2>/dev/null && break
  sleep 0.5
done

echo "==> verifying the served HTML and its assets agree"
HTML="$(curl -fsS "http://127.0.0.1:$PORT/")" || { echo "!! server not responding" >&2; tail -20 "$LOG" >&2; exit 1; }

fail=0
while read -r asset; do
  [ -z "$asset" ] && continue
  code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT$asset")"
  if [ "$code" != "200" ]; then
    echo "!! $code  $asset" >&2
    fail=1
  fi
done <<< "$(printf '%s' "$HTML" | grep -o '/_next/static/[^"]*' | sort -u)"

if [ "$fail" -ne 0 ]; then
  echo "!! The HTML references assets that do not exist. That is the stale-server" >&2
  echo "!! failure: the page will load with no CSS and React will not hydrate." >&2
  exit 1
fi

# The tab bar ships its own layout floor inline. If it is missing, the HTML is
# older than the fix and no amount of CSS work will straighten the bar.
if printf '%s' "$HTML" | grep -q 'nav.tabbar{'; then
  echo "==> tab bar layout floor: present"
else
  echo "!! tab bar layout floor MISSING from the served HTML - serving an old build" >&2
  exit 1
fi

echo "==> OK. $(printf '%s' "$HTML" | grep -o '/_next/static/[^\"]*' | sort -u | wc -l) assets verified, all 200."
echo "==> logs: $LOG"
