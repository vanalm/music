"""Local analysis — stems, structure, and lyrics with no account and no upload.

Every hosted door to the Moises/Music.AI engine turned out to be gated: their
self-serve signup is shut and no Moises consumer tier grants an API key. That
is not a blocker, because the interesting parts run on a Mac:

===============  ==========================================================
Stems            **Demucs** — the model family Moises' own separation is
                 built on. Runs on Apple Silicon via ``--device mps``.
Tempo/structure  **allin1** — beats, downbeats, BPM, and *labelled* segments
                 (intro/verse/chorus/bridge/solo/outro). The closest single
                 tool to "help me finish this song".
Lyrics           **Whisper** — transcription, fast on Apple Silicon.
===============  ==========================================================

These are treated exactly like ffmpeg in ``audio.py``: **external programs that
may be absent**, detected at call time and never imported. The package keeps
its zero-dependency install; the heavy ML stack is opt-in, and a missing tool
produces an install hint rather than an ImportError.

Every command supports ``--dry-run``, which prints the exact argv without
running it. That exists because published CLI flags drift, and seeing the
command before it runs beats debugging it afterwards.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

from .errors import AudioError, MusicStackError


class Tool:
    """An external analysis program, with how to get it and how to call it."""

    def __init__(self, key, binary, install, docs, note=""):
        self.key = key
        self.binary = binary
        self.install = install
        self.docs = docs
        self.note = note

    def which(self):
        return shutil.which(self.binary)

    def require(self):
        found = self.which()
        if not found:
            raise MusicStackError(
                "{} is not installed.\n"
                "  install: {}\n"
                "  docs:    {}{}".format(
                    self.binary,
                    self.install,
                    self.docs,
                    "\n  note:    " + self.note if self.note else "",
                )
            )
        return found


TOOLS = {
    "demucs": Tool(
        "demucs",
        "demucs",
        "pip install -U demucs",
        "https://github.com/adefossez/demucs",
        "On Apple Silicon add --device mps for a large speedup.",
    ),
    "allin1": Tool(
        "allin1",
        "allin1",
        "pip install torch && pip install git+https://github.com/CPJKU/madmom "
        "&& pip install allin1",
        "https://github.com/mir-aidj/all-in-one",
        "madmom must come from git; the PyPI release is too old to build.",
    ),
    "whisper": Tool(
        "whisper",
        "whisper",
        "pip install -U openai-whisper",
        "https://github.com/openai/whisper",
    ),
    "basic-pitch": Tool(
        "basic-pitch",
        "basic-pitch",
        "pip install -U basic-pitch",
        "https://github.com/spotify/basic-pitch",
        "Polyphonic audio-to-MIDI. This is the one that tells you what notes "
        "you played.",
    ),
}

#: Whisper reaches a Mac by several routes, and the argv differs for each.
#: Rather than demand one, detect whichever is already installed and adapt.
#: Ordered fastest-first on Apple Silicon.
WHISPER_VARIANTS = (
    # (binary, kind, install hint)
    ("mlx_whisper", "mlx", "pip install -U mlx-whisper"),
    ("whisper-cli", "cpp", "brew install whisper-cpp"),
    ("whisper-cpp", "cpp", "brew install whisper-cpp"),
    ("whisper", "openai", "pip install -U openai-whisper"),
)


def find_whisper():
    """Return ``(path, binary, kind)`` for the first Whisper found, else None.

    Lets the pipeline use an audio model that is already on the machine
    instead of insisting on one particular packaging of it.
    """
    for binary, kind, _install in WHISPER_VARIANTS:
        found = shutil.which(binary)
        if found:
            return found, binary, kind
    return None


#: mlx_whisper's --model wants a Hub repo or local directory, not a bare
#: size name; the mlx-community conversions follow this naming scheme.
MLX_WHISPER_REPO = "mlx-community/whisper-{}-mlx"

#: Demucs writes to <out>/<model>/<input-stem>/<source>.wav
DEFAULT_DEMUCS_MODEL = "htdemucs"

#: allin1's documented default output directory, relative to the working dir.
ALLIN1_OUTPUT_DIRNAME = "struct"


def _run(argv, *, cwd=None):
    """Run *argv*, streaming nothing, raising with stderr tail on failure."""
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, check=False)
    except OSError as exc:
        raise MusicStackError("Could not execute {}: {}".format(argv[0], exc)) from exc
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        tail = "\n".join(stderr.splitlines()[-8:]) or "(no stderr)"
        raise MusicStackError(
            "{} exited {}:\n{}".format(Path(argv[0]).name, proc.returncode, tail)
        )
    return proc.stdout.decode("utf-8", "replace")


def _check_input(path):
    path = Path(path)
    if not path.exists():
        raise AudioError("No such audio file: {}".format(path))
    return path


def status():
    """Report which local tools are installed. Used by `doctor`."""
    rows = []
    for t in TOOLS.values():
        if t.key == "whisper":
            # Report whichever Whisper packaging analyze would actually use,
            # not just the openai-whisper binary.
            found = find_whisper()
            if found:
                path, binary, _kind = found
                rows.append((t.key, binary, path, t.install))
                continue
        rows.append((t.key, t.binary, t.which(), t.install))
    return rows


# -- stems ----------------------------------------------------------------


def stems_command(path, out_dir, *, model=DEFAULT_DEMUCS_MODEL, device=None,
                  two_stems=None, binary="demucs"):
    """Build the Demucs argv. Separated from execution so --dry-run can show it."""
    argv = [binary, "-n", model, "-o", str(out_dir)]
    if device:
        argv += ["--device", device]
    if two_stems:
        # Isolates one source and groups everything else into a second file.
        argv += ["--two-stems", two_stems]
    argv.append(str(path))
    return argv


def stems(path, out_dir, *, model=DEFAULT_DEMUCS_MODEL, device=None,
          two_stems=None, dry_run=False):
    """Separate *path* into stems with Demucs. Returns the written files."""
    path = _check_input(path)
    out_dir = Path(out_dir)
    argv = stems_command(
        path, out_dir, model=model, device=device, two_stems=two_stems,
        binary=TOOLS["demucs"].binary if dry_run else TOOLS["demucs"].require(),
    )
    if dry_run:
        return {"command": argv}

    out_dir.mkdir(parents=True, exist_ok=True)
    _run(argv)

    # Demucs nests its output; find it rather than assuming the layout held.
    produced = sorted(
        p for p in out_dir.rglob("*.wav") if p.stat().st_size > 0
    )
    if not produced:
        raise MusicStackError(
            "Demucs reported success but wrote no .wav files under {}. "
            "Run again with --dry-run and try the command by hand.".format(out_dir)
        )
    return {"command": argv, "files": [str(p) for p in produced]}


# -- structure ------------------------------------------------------------


def structure_command(path, *, binary="allin1"):
    """Build the allin1 argv.

    allin1 writes to ``./struct`` relative to its working directory and has no
    stable output-dir flag across versions, so :func:`structure` runs it with
    ``cwd`` set to the destination instead of passing one. Only documented
    behaviour, no guessed flags.
    """
    return [binary, str(Path(path).resolve())]


def structure(path, out_dir, *, dry_run=False):
    """Analyse tempo, beats, downbeats, and labelled sections with allin1."""
    path = _check_input(path).resolve()
    out_dir = Path(out_dir)
    argv = structure_command(
        path,
        binary=TOOLS["allin1"].binary if dry_run else TOOLS["allin1"].require(),
    )
    if dry_run:
        return {"command": argv, "cwd": str(out_dir)}

    out_dir.mkdir(parents=True, exist_ok=True)
    _run(argv, cwd=str(out_dir))

    struct_dir = out_dir / ALLIN1_OUTPUT_DIRNAME
    results = sorted(struct_dir.glob("*.json")) if struct_dir.exists() else []
    if not results:
        raise MusicStackError(
            "allin1 finished but wrote no JSON under {}. Run with --dry-run "
            "and try it by hand to see where it put things.".format(struct_dir)
        )
    return {"command": argv, "files": [str(p) for p in results]}


def summarize_structure(json_path):
    """Reduce allin1's JSON to the fields worth reading while writing.

    Returns bpm, section count, total duration, and the labelled sections with
    their durations — the shape you actually reason about when deciding what a
    half-finished song is missing.
    """
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    segments = data.get("segments") or []
    sections = [
        {
            "label": s.get("label"),
            "start": round(float(s.get("start", 0)), 2),
            "end": round(float(s.get("end", 0)), 2),
            "seconds": round(float(s.get("end", 0)) - float(s.get("start", 0)), 2),
        }
        for s in segments
    ]
    labels = [s["label"] for s in sections]
    return {
        "bpm": data.get("bpm"),
        "beats": len(data.get("beats") or []),
        "downbeats": len(data.get("downbeats") or []),
        "duration_seconds": round(sections[-1]["end"], 2) if sections else None,
        "section_count": len(sections),
        "arrangement": " → ".join(labels) if labels else None,
        "missing": sorted(
            {"intro", "verse", "chorus", "bridge", "outro"} - set(labels)
        ),
        "sections": sections,
    }


# -- lyrics ---------------------------------------------------------------


TRANSCRIPT_SUFFIXES = (".txt", ".json", ".srt", ".vtt", ".tsv")


def lyrics_command(path, out_dir, *, model="small", language=None,
                   binary="whisper", kind="openai"):
    """Build the Whisper argv for whichever variant is installed.

    The three packagings take different flags; ``kind`` selects the dialect.
    """
    path, out_dir = str(path), str(out_dir)
    if kind == "cpp":
        # whisper.cpp wants a GGUF/GGML model file, not a model name, and
        # writes alongside the output prefix rather than into a directory.
        argv = [binary, "-f", path, "-otxt", "-oj",
                "-of", os.path.join(out_dir, Path(path).stem)]
        if model and os.path.exists(model):
            argv += ["-m", model]
        if language:
            argv += ["-l", language]
        return argv

    if kind == "mlx":
        # mlx_whisper takes dashed flags, and its --model is a Hub repo or
        # local directory rather than a size name.
        if model and "/" not in model and not os.path.exists(model):
            model = MLX_WHISPER_REPO.format(model)
        argv = [binary, path, "--model", model,
                "--output-dir", out_dir, "--output-format", "all"]
        if language:
            argv += ["--language", language]
        return argv

    # openai-whisper: underscore flags, bare size names.
    argv = [binary, path, "--model", model,
            "--output_dir", out_dir, "--output_format", "all"]
    if language:
        argv += ["--language", language]
    return argv


def lyrics(path, out_dir, *, model="small", language=None, dry_run=False):
    """Transcribe a vocal take with whichever Whisper is on this machine."""
    path = _check_input(path)
    out_dir = Path(out_dir)

    found = find_whisper()
    if found is None:
        if not dry_run:
            hints = "\n".join(
                "  {:<13} {}".format(b, i) for b, _k, i in WHISPER_VARIANTS
            )
            raise MusicStackError(
                "No Whisper installation found. Any of these works:\n" + hints
            )
        binary, kind = "whisper", "openai"
    else:
        _, binary, kind = found

    argv = lyrics_command(
        path, out_dir, model=model, language=language, binary=binary, kind=kind
    )
    if dry_run:
        return {"command": argv, "variant": kind}

    out_dir.mkdir(parents=True, exist_ok=True)
    _run(argv)
    produced = sorted(
        p for p in out_dir.iterdir()
        if p.is_file() and p.suffix in TRANSCRIPT_SUFFIXES
    )
    if not produced:
        raise MusicStackError(
            "Whisper finished but wrote nothing to {}.".format(out_dir)
        )
    return {"command": argv, "variant": kind, "files": [str(p) for p in produced]}


def read_transcript(paths):
    """Pull plain text out of whatever transcript files Whisper produced."""
    for path in paths:
        p = Path(path)
        if p.suffix == ".txt":
            text = p.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                return text
    for path in paths:
        p = Path(path)
        if p.suffix == ".json":
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                continue
            text = (data.get("text") or "").strip()
            if text:
                return text
    return ""


def detect_device():
    """Suggest ``mps`` on Apple Silicon, else leave it to the tool's default."""
    if os.uname().sysname == "Darwin" and os.uname().machine == "arm64":
        return "mps"
    return None


# -- note transcription ---------------------------------------------------


def notes_command(path, out_dir, *, binary="basic-pitch", note_events=True,
                  sonify=False):
    """Build the basic-pitch argv.

    Note the argument order: output directory comes *before* the input, which
    is the opposite of most tools and an easy thing to get backwards.
    """
    argv = [binary, str(out_dir), str(path)]
    if note_events:
        # The CSV is far easier to read than the MIDI binary, and carries the
        # same note starts, ends, and pitches.
        argv.append("--save-note-events")
    if sonify:
        argv.append("--sonify-midi")
    return argv


def notes(path, out_dir, *, sonify=False, dry_run=False):
    """Transcribe *path* to note events with basic-pitch."""
    path = _check_input(path)
    out_dir = Path(out_dir)
    tool = TOOLS["basic-pitch"]
    argv = notes_command(
        path, out_dir,
        binary=tool.binary if dry_run else tool.require(),
        sonify=sonify,
    )
    if dry_run:
        return {"command": argv}

    out_dir.mkdir(parents=True, exist_ok=True)
    _run(argv)
    csvs = sorted(out_dir.glob("*.csv"))
    midis = sorted(out_dir.glob("*.mid")) + sorted(out_dir.glob("*.midi"))
    if not csvs:
        raise MusicStackError(
            "basic-pitch wrote no note-event CSV to {}. It may have produced "
            "only MIDI ({}); re-run with --dry-run and check the flags.".format(
                out_dir, ", ".join(p.name for p in midis) or "none"
            )
        )
    return {
        "command": argv,
        "note_events": str(csvs[0]),
        "midi": str(midis[0]) if midis else None,
        "files": [str(p) for p in csvs + midis],
    }
