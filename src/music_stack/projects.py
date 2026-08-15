"""Per-song project directories.

One song is one directory with a fixed shape, so that six months from now the
provenance of a file is obvious from its path alone: what went in, what the
lossless working copy was, which service produced which stem, and which
harmony takes were hand-exported rather than API-generated.
"""

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from .errors import MusicStackError

#: Every project gets all of these, even when a stage goes unused — an empty
#: directory is a cheap reminder that the stage exists.
SUBDIRS = (
    "input",                  # untouched originals, never written to again
    "normalized",             # lossless 48k/24-bit working copies
    "analysis/music-ai",      # chords, key, tempo, lyrics, structure
    "stems/music-ai",
    "stems/kits",
    "harmonies/manual-kits",  # exported by hand from the Kits web app
    "renders",                # bounces and mixes
    "notes",                  # lyrics, arrangement scratch
)

METADATA_FILE = "project.json"


def slugify(title):
    """Turn a song title into a filesystem-safe slug."""
    normalised = unicodedata.normalize("NFKD", str(title))
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        raise MusicStackError(
            "{!r} has no characters usable in a folder name; give the project "
            "a title with letters or numbers in it.".format(title)
        )
    return slug


def create(root, title, *, exist_ok=False):
    """Create the project tree for *title* under *root*. Returns its path."""
    slug = slugify(title)
    path = Path(root) / slug
    if path.exists() and not exist_ok:
        raise MusicStackError(
            "{} already exists. Pass --exist-ok to add any missing "
            "subdirectories to it.".format(path)
        )
    for sub in SUBDIRS:
        (path / sub).mkdir(parents=True, exist_ok=True)

    meta_path = path / METADATA_FILE
    if not meta_path.exists():
        meta_path.write_text(
            json.dumps(
                {
                    "title": title,
                    "slug": slug,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "jobs": [],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return path


def load(path):
    """Read a project's metadata file."""
    meta_path = Path(path) / METADATA_FILE
    if not meta_path.exists():
        raise MusicStackError("{} is not a project directory".format(path))
    return json.loads(meta_path.read_text(encoding="utf-8"))


def record_job(path, entry):
    """Append a job record to the project's metadata, newest last.

    Called after every remote job so that each project carries its own audit
    trail: which service, which workflow, which job id, when.
    """
    meta_path = Path(path) / METADATA_FILE
    meta = load(path)
    meta.setdefault("jobs", []).append(entry)
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def listing(root):
    """Return the slugs of every project under *root*, sorted."""
    root = Path(root)
    if not root.exists():
        return []
    return sorted(
        p.name for p in root.iterdir() if p.is_dir() and (p / METADATA_FILE).exists()
    )
