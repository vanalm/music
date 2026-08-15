"""Audio conversion and inspection through ffmpeg / ffprobe.

Both binaries are treated as *external tools that may be absent*: every entry
point checks for them and raises :class:`AudioError` with an install hint
rather than letting a ``FileNotFoundError`` escape. That matters because a
fresh machine will not have them, and the failure should read as "run the
bootstrap script", not as a crash.
"""

import json
import shutil
import subprocess
from pathlib import Path

from .errors import AudioError

#: The working format for everything downstream. Services accept a wide range
#: of inputs, but normalising once up front means every later step — stem
#: separation, harmony, mixing — sees identical sample rate and bit depth.
TARGET_RATE = 48000
TARGET_BITS = 24

_BIT_DEPTH_CODEC = {16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_s32le"}


def which(binary):
    """Return the resolved path to *binary*, or None."""
    return shutil.which(binary)


def require(binary):
    """Return the path to *binary* or explain how to install it."""
    found = which(binary)
    if not found:
        raise AudioError(
            "{0} was not found on PATH.\n"
            "Install it with `brew install ffmpeg` (macOS) or run "
            "./scripts/bootstrap-macos.sh, which installs it for you.".format(binary)
        )
    return found


def _run(argv):
    """Run *argv*, returning stdout; raise AudioError with stderr on failure."""
    try:
        proc = subprocess.run(argv, capture_output=True, check=False)
    except OSError as exc:
        raise AudioError("Could not execute {}: {}".format(argv[0], exc)) from exc
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        # ffmpeg is chatty; the last few lines carry the actual reason.
        tail = "\n".join(stderr.splitlines()[-6:]) or "(no stderr)"
        raise AudioError(
            "{} exited {}:\n{}".format(Path(argv[0]).name, proc.returncode, tail)
        )
    return proc.stdout


def inspect(path):
    """Return ffprobe's view of *path* as a dict.

    Includes a flattened ``summary`` of the first audio stream so callers do
    not have to dig through ffprobe's nesting for the common fields.
    """
    path = Path(path)
    if not path.exists():
        raise AudioError("No such audio file: {}".format(path))
    ffprobe = require("ffprobe")
    raw = _run(
        [
            ffprobe,
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise AudioError("ffprobe returned output that is not JSON") from exc

    audio = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None
    )
    fmt = data.get("format", {})
    data["summary"] = {
        "path": str(path),
        "codec": (audio or {}).get("codec_name"),
        "sample_rate": _int_or_none((audio or {}).get("sample_rate")),
        "channels": (audio or {}).get("channels"),
        "bit_depth": _int_or_none(
            (audio or {}).get("bits_per_raw_sample")
            or (audio or {}).get("bits_per_sample")
        ),
        "duration_seconds": _float_or_none(fmt.get("duration")),
        "size_bytes": _int_or_none(fmt.get("size")),
    }
    return data


def normalize(src, dest, *, rate=TARGET_RATE, bit_depth=TARGET_BITS, overwrite=False):
    """Transcode *src* to a lossless WAV working copy at *dest*.

    This is a format conversion, not loudness normalisation — no gain is
    applied and nothing is resampled destructively beyond the sample-rate
    change requested. The point is a predictable, lossless intermediate.
    """
    src, dest = Path(src), Path(dest)
    if not src.exists():
        raise AudioError("No such audio file: {}".format(src))
    if dest.exists() and not overwrite:
        raise AudioError(
            "{} already exists. Pass --overwrite to replace it.".format(dest)
        )
    codec = _BIT_DEPTH_CODEC.get(bit_depth)
    if codec is None:
        raise AudioError(
            "Unsupported bit depth {}; choose one of {}.".format(
                bit_depth, ", ".join(str(k) for k in sorted(_BIT_DEPTH_CODEC))
            )
        )
    ffmpeg = require("ffmpeg")
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-y" if overwrite else "-n",
            "-i", str(src),
            "-vn",                  # drop cover art; it confuses some services
            "-map_metadata", "-1",  # strip tags so nothing personal rides along
            "-acodec", codec,
            "-ar", str(rate),
            str(dest),
        ]
    )
    return dest


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
