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

# Fail here rather than after a five-minute build. A frontend pointed at an API
# it cannot reach looks entirely healthy until someone runs OCR.
if [ "${SKIP_API_CHECK:-0}" != "1" ]; then
  echo "==> checking the API answers at $API_BASE"
  if ! curl -fsS --max-time 5 "$API_BASE/health" > /dev/null 2>&1; then
    echo "!! $API_BASE/health did not answer." >&2
    echo "!! Point API_BASE at an address THIS HOST can reach - inside compose that" >&2
    echo "!! is http://api:8000, on the host it is http://127.0.0.1:8000." >&2
    echo "!! Re-run with SKIP_API_CHECK=1 to deploy anyway." >&2
    exit 1
  fi
fi

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
# API_BASE is needed at RUNTIME as well as at build time, and the two are for
# different things. The build bakes it into the /api/:path* rewrite. The server
# reads it again for the route handlers that bypass that rewrite so a slow
# vision read is not cut off at the rewrite's 30s limit: /api/extract,
# /api/extract/batch and /api/agent/stream (see app/lib/proxyUpstream.ts).
# Omit it here and those three fall back to localhost:8001, so OCR fails with
# "Extraction proxy error" while every other page looks perfectly healthy.
API_BASE="$API_BASE" PORT="$PORT" HOSTNAME="$HOSTNAME_BIND" \
  nohup node .next/standalone/server.js > "$LOG" 2>&1 &
for _ in $(seq 1 60); do
  curl -fsS -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/" 2>/dev/null && break
  sleep 0.5
done

echo "==> verifying the served HTML and its assets agree"
HTML="$(curl -fsS "http://127.0.0.1:$PORT/")" || { echo "!! server not responding" >&2; tail -20 "$LOG" >&2; exit 1; }

# Match the asset path by its own alphabet and require a real file extension.
# Not `[^"]*`: every one of these URLs also appears inside React's flight
# payload as JSON, escaped to ...css\" — and a "anything but a quote" match
# happily swallows that backslash, then asks the server for a filename ending
# in \. Next answers 308 (normalising the path) and the check reports a healthy
# deploy as broken.
ASSETS="$(printf '%s' "$HTML" \
  | grep -oE '/_next/static/[A-Za-z0-9._/-]+\.(js|css|woff2?|png|svg|ico)' \
  | sort -u)"

if [ -z "$ASSETS" ]; then
  echo "!! No /_next/static assets referenced at all - that HTML is not the app." >&2
  exit 1
fi

fail=0
while read -r asset; do
  [ -z "$asset" ] && continue
  code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT$asset")"
  if [ "$code" != "200" ]; then
    echo "!! $code  $asset" >&2
    fail=1
  fi
done <<< "$ASSETS"

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

# The OCR route reads API_BASE from this process's environment, so prove the
# running server resolved it rather than trusting that we exported it. An empty
# POST is rejected by the upstream, which is fine - what matters is whether the
# proxy reached an upstream at all. A connection failure comes back as
# "Extraction proxy error", which is exactly the symptom being guarded against.
echo "==> checking the OCR proxy can reach the API"
EXTRACT_BODY="$(curl -s --max-time 20 -X POST "http://127.0.0.1:$PORT/api/extract" || true)"
if printf '%s' "$EXTRACT_BODY" | grep -qi 'Extraction proxy error'; then
  echo "!! The server cannot reach the API on the extract route:" >&2
  printf '   %s\n' "$EXTRACT_BODY" >&2
  echo "!! API_BASE was not in the SERVER's environment (it is needed at runtime," >&2
  echo "!! not only for the build). Check the start line and $LOG." >&2
  exit 1
fi
grep -m1 'upstream configured' "$LOG" 2>/dev/null | sed 's/^/    /' || true

echo "==> OK. $(printf '%s\n' "$ASSETS" | wc -l) assets verified, all 200."
echo "==> logs: $LOG"
