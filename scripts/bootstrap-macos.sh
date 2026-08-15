#!/usr/bin/env bash
#
# Set up music-stack on a Mac.
#
# Deliberately does NOT pipe Homebrew's remote installer into your shell. If
# Homebrew is missing this stops and tells you, rather than executing a script
# fetched from the internet on your behalf.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m    %s\033[0m\n' "$*"; }
die()  { printf '\n\033[31merror: %s\033[0m\n' "$*" >&2; exit 1; }

# -- 1. platform ------------------------------------------------------------

say "Checking platform"
[[ "$(uname -s)" == "Darwin" ]] || die "This script is for macOS. On Linux install ffmpeg and python3 with your package manager, then: python3 -m venv .venv && .venv/bin/pip install -e ."
echo "    macOS $(sw_vers -productVersion 2>/dev/null || echo '?') on $(uname -m)"

# -- 2. homebrew ------------------------------------------------------------

say "Checking Homebrew"
if ! command -v brew >/dev/null 2>&1; then
  die "Homebrew is not installed.
    Install it yourself from https://brew.sh, then re-run this script.
    This script will not run a remote installer for you."
fi
echo "    $(brew --version | head -1)"

# -- 3. system packages -----------------------------------------------------

say "Installing system packages"
for pkg in ffmpeg python@3.13 jq; do
  if brew list --formula "$pkg" >/dev/null 2>&1; then
    echo "    $pkg already installed"
  else
    echo "    installing $pkg"
    brew install "$pkg"
  fi
done

command -v ffmpeg  >/dev/null || die "ffmpeg still not on PATH after install"
command -v ffprobe >/dev/null || die "ffprobe still not on PATH after install"

# -- 4. python --------------------------------------------------------------

say "Setting up the virtualenv"
PY="$(command -v python3.13 || command -v python3)"
echo "    using $PY ($($PY --version))"

if [[ -d .venv ]]; then
  echo "    .venv exists; reusing it"
else
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

say "Installing music-stack"
# No third-party dependencies are fetched here -- the package is stdlib-only.
# See docs/architecture.md for why that is deliberate.
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -e .
echo "    installed $(music-stack --version)"

# -- 5. credentials file ----------------------------------------------------

say "Preparing .env"
if [[ -f .env ]]; then
  echo "    .env already exists; leaving it untouched"
else
  cp .env.example .env
  chmod 600 .env
  echo "    created .env from .env.example (mode 600, gitignored)"
fi

# -- 6. verify --------------------------------------------------------------

say "Running the test suite"
PYTHONPATH=src:tests python -m unittest discover -s tests

say "Diagnostics"
# doctor exits non-zero when something is missing; that is informational here,
# not a bootstrap failure, so don't let -e abort on it.
music-stack doctor || true

cat <<'EOF'

Bootstrap complete.

Next:
  1. Open the signup pages:   ./scripts/open-account-pages-macos.sh
  2. Paste your keys:         $EDITOR .env
  3. Re-check:                source .venv/bin/activate && music-stack doctor
  4. First song:              music-stack project new "Working Title"

Remember to `source .venv/bin/activate` in each new terminal.
EOF
