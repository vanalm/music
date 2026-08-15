#!/usr/bin/env bash
#
# Open the signup / API-key pages for each service, in the order recommended in
# docs/services-and-costs.md. Opens tabs only -- creates no accounts, buys
# nothing, and stores nothing.
#
set -euo pipefail

[[ "$(uname -s)" == "Darwin" ]] || { echo "macOS only; open these URLs manually:"; }

urls=(
  "https://music.ai/"                  # 1. Music.AI - developer credits
  "https://docs.music.ai/"             #    API reference
  "https://www.kits.ai/api"            # 2. Kits - API access
  "https://app.kits.ai/"               #    Kits web app (Harmony Generator)
  "https://suno.com/platform"          # 3. Suno - read the API docs signed in
)

for url in "${urls[@]}"; do
  echo "  $url"
  if command -v open >/dev/null 2>&1; then
    open "$url"
    sleep 1   # let the browser keep tab order stable
  fi
done

cat <<'EOF'

Recommended order (see docs/services-and-costs.md):

  1. Music.AI  - buy the smallest credit pack; process one short demo first.
  2. Kits      - API access, plus whichever app tier allows harmony exports.
                 Note the API is served from arpeggi.io, not kits.ai.
  3. Suno      - last. Read the authenticated API reference before paying.

Then paste the keys into .env and run: music-stack doctor
EOF
