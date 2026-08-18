"""The one-command pipeline: audio in, songwriting brief out.

``music-stack analyze --input demo.m4a --title "Working Title"`` runs every
stage that this machine can support, skips the rest without complaint, and
writes a single readable brief.

The brief is the actual deliverable. Stems and JSON are intermediate artifacts;
what you want at 11pm with a half-finished song is one page telling you the
tempo, the arrangement you actually played, what sections are missing, and what
you sang — with the open questions spelled out.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from . import audio, local_tools, projects

#: Sections a conventional song usually has. Absence is a prompt, not a verdict.
EXPECTED_SECTIONS = ("intro", "verse", "chorus", "bridge", "outro")


def analyze(root, input_path, *, title=None, skip=(), dry_run=False, log=print):
    """Run the whole local pipeline over *input_path*. Returns a result dict."""
    input_path = Path(input_path).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    title = title or input_path.stem.replace("_", " ").replace("-", " ").title()
    project_dir = projects.create(root, title, exist_ok=True)
    slug = project_dir.name

    result = {
        "title": title,
        "slug": slug,
        "project": str(project_dir),
        "source": str(input_path),
        "stages": {},
        "skipped": [],
    }

    # -- 1. preserve the original ----------------------------------------
    kept = project_dir / "input" / input_path.name
    if not dry_run and not kept.exists():
        kept.write_bytes(input_path.read_bytes())
    result["input"] = str(kept)

    # -- 2. lossless working copy ----------------------------------------
    normalized = project_dir / "normalized" / "{}-48k-24bit.wav".format(slug)
    if "normalize" in skip:
        result["skipped"].append("normalize")
    elif dry_run:
        result["stages"]["normalize"] = {"would_write": str(normalized)}
    else:
        log("normalizing…")
        audio.normalize(kept, normalized, overwrite=True)
        result["stages"]["normalize"] = {
            "file": str(normalized),
            "summary": audio.inspect(normalized)["summary"],
        }

    # In a dry run nothing has been copied or transcoded yet, so fall back to
    # the file the user actually pointed at rather than a path that will only
    # exist on a real run.
    if normalized.exists():
        working = normalized
    elif kept.exists():
        working = kept
    else:
        working = input_path

    # -- 3. structure: tempo, beats, labelled sections --------------------
    if "structure" in skip or not local_tools.TOOLS["allin1"].which():
        result["skipped"].append("structure")
        log("skipping structure (allin1 not installed)")
    else:
        log("analysing structure…")
        out = project_dir / "analysis"
        stage = local_tools.structure(working, out, dry_run=dry_run)
        if not dry_run and stage.get("files"):
            stage["summary"] = local_tools.summarize_structure(stage["files"][0])
        result["stages"]["structure"] = stage

    # -- 4. stems ---------------------------------------------------------
    vocal_stem = None
    if "stems" in skip or not local_tools.TOOLS["demucs"].which():
        result["skipped"].append("stems")
        log("skipping stems (demucs not installed)")
    else:
        log("separating stems… (this is the slow one)")
        out = project_dir / "stems" / "local"
        stage = local_tools.stems(
            working, out, device=local_tools.detect_device(), dry_run=dry_run
        )
        result["stages"]["stems"] = stage
        for path in stage.get("files", []):
            if Path(path).stem == "vocals":
                vocal_stem = path
                break

    # -- 5. lyrics --------------------------------------------------------
    # Transcribe the isolated vocal when we have one: a separated stem gives a
    # markedly better transcript than a full mix with instruments fighting it.
    if "lyrics" in skip or (local_tools.find_whisper() is None and not dry_run):
        result["skipped"].append("lyrics")
        log("skipping lyrics (no Whisper installation found)")
    else:
        source = vocal_stem or working
        log("transcribing {}…".format("isolated vocal" if vocal_stem else "full mix"))
        out = project_dir / "notes" / "lyrics"
        stage = local_tools.lyrics(source, out, dry_run=dry_run)
        stage["transcribed"] = str(source)
        stage["from_isolated_vocal"] = bool(vocal_stem)
        if not dry_run:
            stage["text"] = local_tools.read_transcript(stage.get("files", []))
        result["stages"]["lyrics"] = stage

    if dry_run:
        return result

    # -- 6. the brief -----------------------------------------------------
    result["brief"] = render(result)
    brief_path = project_dir / "brief.md"
    brief_path.write_text(result["brief"], encoding="utf-8")
    (project_dir / "brief.json").write_text(
        json.dumps(_serialisable(result), indent=2) + "\n", encoding="utf-8"
    )
    result["brief_path"] = str(brief_path)

    # The visual surface: one self-contained HTML file. Never fatal -- a
    # report failure must not throw away a finished analysis.
    try:
        from . import report as report_mod

        result["report_path"] = str(
            report_mod.write(result, project_dir, audio_path=working)
        )
    except Exception as exc:  # pragma: no cover - defensive
        log("report generation failed: {}".format(exc))
    projects.record_job(
        project_dir,
        {
            "service": "local",
            "workflow": "analyze",
            "job_id": None,
            "output": str(brief_path),
            "at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return result


def render(result):
    """Turn the analysis into the one page worth reading."""
    lines = ["# {}".format(result["title"]), ""]

    norm = result["stages"].get("normalize", {}).get("summary") or {}
    if norm:
        duration = norm.get("duration_seconds")
        lines.append(
            "**Source** · {} · {} Hz · {} ch{}".format(
                norm.get("codec") or "?",
                norm.get("sample_rate") or "?",
                norm.get("channels") or "?",
                " · {:d}:{:02d}".format(int(duration // 60), int(duration % 60))
                if duration
                else "",
            )
        )
        lines.append("")

    structure = result["stages"].get("structure", {}).get("summary")
    if structure:
        lines += ["## Structure", ""]
        if structure.get("bpm"):
            lines.append("- **Tempo** — {} BPM".format(structure["bpm"]))
        if structure.get("arrangement"):
            lines.append("- **Arrangement** — {}".format(structure["arrangement"]))
        if structure.get("sections"):
            lines.append("")
            lines.append("| Section | Start | Length |")
            lines.append("|---|---|---|")
            for s in structure["sections"]:
                lines.append(
                    "| {} | {} | {}s |".format(
                        s["label"], _clock(s["start"]), s["seconds"]
                    )
                )
        missing = structure.get("missing") or []
        if missing:
            lines += [
                "",
                "**Not present yet:** {}".format(", ".join(missing)),
            ]
        lines.append("")

    lyrics = result["stages"].get("lyrics", {})
    if lyrics.get("text"):
        lines += ["## Lyrics as sung", ""]
        if lyrics.get("from_isolated_vocal"):
            lines.append("*Transcribed from the isolated vocal stem.*")
        else:
            lines.append(
                "*Transcribed from the full mix — expect errors where "
                "instruments mask the vocal.*"
            )
        lines += ["", "```", lyrics["text"], "```", ""]

    stems = result["stages"].get("stems", {})
    if stems.get("files"):
        lines += ["## Stems", ""]
        for path in stems["files"]:
            lines.append("- `{}`".format(path))
        lines.append("")

    lines += ["## To finish this", ""]
    for question in questions(result):
        lines.append("- {}".format(question))
    lines.append("")

    if result["skipped"]:
        lines += [
            "---",
            "",
            "*Stages skipped (tool not installed): {}. "
            "Run `music-stack local doctor`.*".format(", ".join(result["skipped"])),
            "",
        ]
    return "\n".join(lines)


def questions(result):
    """Concrete prompts derived from what the analysis actually found.

    Deliberately questions rather than instructions — the analysis knows what
    is missing structurally, it does not know what the song is about.
    """
    out = []
    structure = result["stages"].get("structure", {}).get("summary") or {}
    missing = structure.get("missing") or []
    sections = structure.get("sections") or []
    labels = [s["label"] for s in sections]

    if "chorus" in missing:
        out.append(
            "There's no identifiable chorus. Is the hook still unwritten, or is "
            "it there but not lifting enough to register as a separate section?"
        )
    if "bridge" in missing and "chorus" not in missing:
        out.append(
            "No bridge. Where would the song benefit from leaving the loop — "
            "and what does it need to say there that the verses don't?"
        )
    if labels.count("verse") == 1:
        out.append(
            "Only one verse. What's the second one about — does it advance the "
            "story or restate it from a different angle?"
        )
    if "outro" in missing:
        out.append("No outro — does it end, or does it currently just stop?")

    duration = structure.get("duration_seconds")
    if duration and duration < 90:
        out.append(
            "It runs {:.0f}s. That's a sketch, not an arrangement — which "
            "section wants extending first?".format(duration)
        )

    lyrics = result["stages"].get("lyrics", {})
    if lyrics.get("text"):
        words = len(lyrics["text"].split())
        if words < 40:
            out.append(
                "Only ~{} words transcribed. Are large stretches still "
                "hummed or wordless?".format(words)
            )

    if not out:
        out.append(
            "The structure is complete. What's weakest — the lyric, the "
            "melody, or the arrangement?"
        )
    out.append(
        "Paste this brief into a chat to work through the answers."
    )
    return out


def _clock(seconds):
    seconds = int(seconds or 0)
    return "{:d}:{:02d}".format(seconds // 60, seconds % 60)


def _serialisable(result):
    """Drop the rendered markdown from the JSON twin — it's in brief.md."""
    return {k: v for k, v in result.items() if k != "brief"}
