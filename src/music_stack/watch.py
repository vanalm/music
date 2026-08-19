"""A drop folder: drag audio in from Finder, get an analyzed project out.

``music-stack watch`` polls a ``dropbox/`` directory. Any audio file that
lands there gets run through the full ``analyze`` pipeline; the original is
then moved to ``dropbox/done/`` so it is never processed twice, and every
output lands in ``projects/<slug>/`` exactly as if you had run ``analyze``
by hand. A file that fails moves to ``dropbox/failed/`` instead of being
retried forever.

Two details that matter more than they look:

* **Stability check.** A file being copied in — AirDrop, Finder, a browser
  download — exists long before its bytes have all arrived. Grabbing it
  immediately would analyze a truncated file. So a candidate is only taken
  once its size has stopped changing between two looks.
* **Polling, not fsevents.** A filesystem-watch API would need a third-party
  package; a few-second poll needs nothing and is imperceptible next to a
  stem-separation run.
"""

import shutil
import subprocess
import time
from pathlib import Path

from .errors import MusicStackError


def notify(title, message):
    """Post a macOS notification, silently doing nothing when unavailable.

    The watcher runs unattended in the background; without this, a finished
    or failed drop is invisible unless someone is tailing the log.
    """
    osascript = shutil.which("osascript")
    if not osascript:
        return
    script = 'display notification "{}" with title "{}"'.format(
        str(message).replace("\\", "\\\\").replace('"', '\\"'),
        str(title).replace("\\", "\\\\").replace('"', '\\"'),
    )
    try:
        subprocess.run([osascript, "-e", script], capture_output=True,
                       timeout=10)
    except Exception:
        pass

#: What counts as droppable audio (or video carrying audio).
AUDIO_SUFFIXES = (
    ".m4a", ".mp3", ".wav", ".flac", ".aiff", ".aif", ".ogg",
    ".mp4", ".mov",
)

DONE_DIR = "done"
FAILED_DIR = "failed"


def scan(drop_dir):
    """Return processable audio files currently sitting in *drop_dir*.

    Skips dotfiles (AirDrop writes ``.Filename`` temporaries mid-transfer),
    the ``done``/``failed`` subfolders, and anything that is not audio.
    """
    drop_dir = Path(drop_dir)
    if not drop_dir.exists():
        return []
    return sorted(
        p
        for p in drop_dir.iterdir()
        if p.is_file()
        and not p.name.startswith(".")
        and p.suffix.lower() in AUDIO_SUFFIXES
    )


def is_stable(path, *, wait=1.0, sleep=time.sleep):
    """True once *path*'s size stops changing — i.e. the copy has finished."""
    path = Path(path)
    try:
        before = path.stat().st_size
        sleep(wait)
        after = path.stat().st_size
    except OSError:
        return False
    return before == after and after > 0


def _move_to(path, subdir):
    """Move *path* into *subdir* beside it, never clobbering an earlier one."""
    path = Path(path)
    dest_dir = path.parent / subdir
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / path.name
    counter = 1
    while dest.exists():
        dest = dest_dir / "{}-{}{}".format(path.stem, counter, path.suffix)
        counter += 1
    shutil.move(str(path), str(dest))
    return dest


def process(path, projects_root, *, analyze_fn=None, log=print,
            notify_fn=None):
    """Analyze one dropped file and file the original under ``done/``.

    Returns the ``analyze`` result dict, or ``None`` when the file failed and
    was moved to ``failed/`` — the watcher keeps going either way, because one
    bad file must not stall the folder.
    """
    if analyze_fn is None:
        from . import brief

        analyze_fn = brief.analyze
    path = Path(path)
    if notify_fn is None:
        notify_fn = notify
    notify_fn("music-stack", "analyzing {}…".format(path.name))
    try:
        result = analyze_fn(projects_root, path, log=log)
    except Exception as exc:
        log("FAILED {}: {}".format(path.name, exc))
        _move_to(path, FAILED_DIR)
        notify_fn("music-stack", "FAILED {} — moved to failed/".format(path.name))
        return None
    _move_to(path, DONE_DIR)
    log(
        "done: {} -> {}".format(
            path.name, result.get("report_path") or result.get("brief_path")
        )
    )
    notify_fn(
        "music-stack", "done: {} — report is ready".format(path.name)
    )
    return result


def run_once(drop_dir, projects_root, *, analyze_fn=None, log=print,
             stability_wait=1.0, sleep=time.sleep, notify_fn=None):
    """Process everything currently in the folder. Returns the results."""
    results = []
    for candidate in scan(drop_dir):
        if not is_stable(candidate, wait=stability_wait, sleep=sleep):
            log("waiting for {} to finish copying…".format(candidate.name))
            continue
        results.append(
            process(candidate, projects_root, analyze_fn=analyze_fn, log=log,
                    notify_fn=notify_fn)
        )
    return results


def run_forever(drop_dir, projects_root, *, interval=3.0, analyze_fn=None,
                log=print, sleep=time.sleep, notify_fn=None):
    """Poll until interrupted. Ctrl-C exits cleanly."""
    drop_dir = Path(drop_dir)
    drop_dir.mkdir(parents=True, exist_ok=True)
    log("watching {} — drop audio files in; Ctrl-C to stop".format(drop_dir))
    try:
        while True:
            run_once(drop_dir, projects_root, analyze_fn=analyze_fn, log=log,
                     sleep=sleep, notify_fn=notify_fn)
            sleep(interval)
    except KeyboardInterrupt:
        log("\nstopped.")
