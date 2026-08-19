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
#     Python >= 3.12 — it gets its own Python 3.11 venv. It CANNOT share a
#     venv with allin1, whose stack needs numpy >= 1.25.
#   * allin1 (structure/tempo) needs madmom from git and natten==0.14.x,
#     in its own 3.11 venv with numpy 1.26 and demucs (it shells out to
#     `python -m demucs.separate` with its own interpreter).
#     natten compiles against torch; expect several minutes.
#
set -uo pipefail

TOOLS_VENV="${MUSIC_STACK_TOOLS_VENV:-$HOME/.venvs/music-tools}"
BP_VENV="${MUSIC_STACK_BP_VENV:-$HOME/.venvs/basic-pitch}"
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

ensure_venv() {
  # ensure_venv <path>: create a Python 3.11 venv there if absent.
  local venv="$1" py
  [[ -x "$venv/bin/python" ]] && return 0
  if ! py="$(find_py311)"; then
    warn "No Python 3.11 found (pyenv install 3.11 or brew install python@3.11)"
    return 1
  fi
  say "Creating venv at $venv (using $py)"
  "$py" -m venv "$venv" && "$venv/bin/pip" install -q -U pip
}

link_tool() {
  # link_tool <venv> <name>: expose a venv binary on PATH.
  local venv="$1" name="$2"
  mkdir -p "$LINK_DIR"
  ln -sf "$venv/bin/$name" "$LINK_DIR/$name"
  echo "    linked $LINK_DIR/$name -> $venv/bin/$name"
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
elif ensure_venv "$BP_VENV"; then
  if "$BP_VENV/bin/pip" install -q basic-pitch; then
    link_tool "$BP_VENV" basic-pitch
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
elif ensure_venv "$TOOLS_VENV"; then
  # Ordering matters, painfully:
  #   * torch is pinned to 2.1.x — natten 0.14.6 is C++ from the same era
  #     and does not compile against newer torch headers.
  #   * natten's setup.py imports torch, hence --no-build-isolation.
  #   * allin1 must go BEFORE the natten pin: its resolver drags in the
  #     newest natten, which then needs to be forced back down.
  # setuptools<81: natten's un-isolated build imports pkg_resources,
  # which setuptools 81+ removed.
  # demucs must ALSO live in this venv: allin1 shells out to
  # `python -m demucs.separate` with its own interpreter.
  if "$TOOLS_VENV/bin/pip" install -q "setuptools<81" wheel "torch==2.1.*" \
     && "$TOOLS_VENV/bin/pip" install -q "git+https://github.com/CPJKU/madmom" \
     && "$TOOLS_VENV/bin/pip" install -q allin1 demucs \
     && "$TOOLS_VENV/bin/pip" install -q --no-build-isolation \
          --force-reinstall --no-deps "natten==0.14.6" \
     && "$TOOLS_VENV/bin/pip" install -q "numpy==1.26.4" "scipy>=1.13" \
     && "$TOOLS_VENV/bin/python" -c "import madmom, demucs, allin1" 2>/dev/null; then
    link_tool "$TOOLS_VENV" allin1
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
