#!/usr/bin/env bash
#
# Install the optional ML analysis tools — the "everything works" step.
#
# The core package stays zero-dependency; these are external programs that
# music-stack discovers on PATH (see CLAUDE.md). Each one is optional and
# independent: a failure here removes a section from the brief, never the
# brief itself. Re-running is safe and skips what is already installed.
#
# Hard-won version notes, encoded so nobody rediscovers them at 1am:
#   * demucs (stems) installs fine on any modern Python.
#   * Whisper: if none is present we install mlx-whisper (Apple Silicon) —
#     any of mlx_whisper / whisper-cli / whisper-cpp / whisper is detected.
#   * basic-pitch (notes/chords) pins numpy<1.24, which does not build on
#     Python >= 3.12 — it gets its own Python 3.11 venv.
#   * allin1 (structure/tempo) needs madmom from git and natten==0.14.x,
#     both from the same era — it shares the 3.11 venv for that reason.
#     natten compiles against torch; expect several minutes.
#
set -uo pipefail

TOOLS_VENV="${MUSIC_STACK_TOOLS_VENV:-$HOME/.venvs/music-tools}"
LINK_DIR="${MUSIC_STACK_LINK_DIR:-/opt/homebrew/bin}"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m    %s\033[0m\n' "$*"; }

fail_count=0

# -- an older Python for the tools that need one ----------------------------

find_py311() {
  for cand in "$HOME/.pyenv/versions/3.11"*/bin/python3 \
              "$(command -v python3.11 || true)"; do
    [[ -n "$cand" && -x "$cand" ]] && { echo "$cand"; return 0; }
  done
  return 1
}

ensure_tools_venv() {
  [[ -x "$TOOLS_VENV/bin/python" ]] && return 0
  local py
  if ! py="$(find_py311)"; then
    warn "No Python 3.11 found (pyenv install 3.11 or brew install python@3.11)"
    return 1
  fi
  say "Creating tools venv at $TOOLS_VENV (using $py)"
  "$py" -m venv "$TOOLS_VENV" && "$TOOLS_VENV/bin/pip" install -q -U pip
}

link_tool() {
  # Expose a venv binary on PATH without activating anything.
  local name="$1"
  mkdir -p "$LINK_DIR"
  ln -sf "$TOOLS_VENV/bin/$name" "$LINK_DIR/$name"
  echo "    linked $LINK_DIR/$name -> $TOOLS_VENV/bin/$name"
}

# -- demucs: stems ----------------------------------------------------------

say "demucs (stem separation)"
if command -v demucs >/dev/null 2>&1; then
  echo "    already installed"
else
  python3 -m pip install -U demucs || { warn "demucs failed"; ((fail_count++)); }
fi

# -- whisper: lyrics --------------------------------------------------------

say "Whisper (lyric transcription)"
if command -v mlx_whisper >/dev/null 2>&1 || command -v whisper-cli >/dev/null 2>&1 \
   || command -v whisper-cpp >/dev/null 2>&1 || command -v whisper >/dev/null 2>&1; then
  echo "    already installed"
elif [[ "$(uname -m)" == "arm64" ]]; then
  python3 -m pip install -U mlx-whisper || { warn "mlx-whisper failed"; ((fail_count++)); }
else
  python3 -m pip install -U openai-whisper || { warn "openai-whisper failed"; ((fail_count++)); }
fi

# -- basic-pitch: notes and chords (needs Python <= 3.11) -------------------

say "basic-pitch (notes and chords)"
if command -v basic-pitch >/dev/null 2>&1; then
  echo "    already installed"
elif ensure_tools_venv; then
  if "$TOOLS_VENV/bin/pip" install -q basic-pitch; then
    link_tool basic-pitch
  else
    warn "basic-pitch failed to install"; ((fail_count++))
  fi
else
  ((fail_count++))
fi

# -- allin1: structure and tempo (same-era deps, same venv) -----------------

say "allin1 (structure, tempo, sections)"
if command -v allin1 >/dev/null 2>&1; then
  echo "    already installed"
elif ensure_tools_venv; then
  # natten's setup.py imports torch, so it must see the venv's torch:
  # install torch first and disable pip's build isolation for natten.
  if "$TOOLS_VENV/bin/pip" install -q torch \
     && "$TOOLS_VENV/bin/pip" install -q "git+https://github.com/CPJKU/madmom" \
     && "$TOOLS_VENV/bin/pip" install -q --no-build-isolation "natten==0.14.6" \
     && "$TOOLS_VENV/bin/pip" install -q allin1 \
     && "$TOOLS_VENV/bin/python" -c "import allin1" 2>/dev/null; then
    link_tool allin1
  else
    warn "allin1 failed — the brief simply skips structure until it works"
    ((fail_count++))
  fi
else
  ((fail_count++))
fi

# -- verify -----------------------------------------------------------------

say "Result"
if command -v music-stack >/dev/null 2>&1; then
  music-stack local doctor || true
else
  warn "music-stack itself is not on PATH — run scripts/bootstrap-macos.sh first"
fi

if (( fail_count > 0 )); then
  warn "$fail_count tool(s) did not install; everything else still works."
fi
