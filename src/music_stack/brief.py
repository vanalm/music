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
import re
from collections import Counter
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
            stage["segments"] = local_tools.read_transcript_segments(
                stage.get("files", [])
            )
        result["stages"]["lyrics"] = stage

    # -- 6. chords: what to actually play ---------------------------------
    # The playing payoff, not just the writing one: transcribe the
    # instruments and name the chords, so the song can be learned back.
    # Prefer the "other" stem when demucs made one — that is where the
    # guitar lives once vocals, bass, and drums are stripped away.
    if "chords" in skip or not local_tools.TOOLS["basic-pitch"].which():
        result["skipped"].append("chords")
        log("skipping chords (basic-pitch not installed)")
    else:
        instrumental = None
        for path in (result["stages"].get("stems") or {}).get("files", []):
            if Path(path).stem == "other":
                instrumental = path
                break
        source = instrumental or working
        log(
            "transcribing chords from {}…".format(
                "instrumental stem" if instrumental else "full mix"
            )
        )
        try:
            stage = local_tools.notes(
                source, project_dir / "notes" / "chords", dry_run=dry_run
            )
            stage["transcribed"] = str(source)
            stage["from_instrumental_stem"] = bool(instrumental)
            if not dry_run:
                stage["chords"] = detect_chords(stage.get("note_events"))
                stage["notes"] = detect_notes(stage.get("note_events"))
            result["stages"]["chords"] = stage
        except Exception as exc:
            # A failed transcription costs one section, never the brief.
            result["skipped"].append("chords")
            log("chord transcription failed, continuing: {}".format(exc))

    if dry_run:
        return result

    # -- 7. the brief -----------------------------------------------------
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


def detect_chords(note_events_path, *, min_duration=0.09, min_notes=3,
                  min_seconds=0.35):
    """Name the chords in a basic-pitch note_events file, with fingerings.

    ``min_notes=3`` because on a whole song two-note groupings are mostly
    transcription bleed; real strummed chords bring at least a triad. And
    ``min_seconds`` drops groupings that ring for less than a third of a
    second — over four minutes those are strum transients and hammer-on
    smear, and they bury the actual progression in noise.
    """
    from . import chords as chords_mod, notes as notes_mod

    if not note_events_path:
        return []
    events = notes_mod.read_note_events(note_events_path)
    events = notes_mod.filter_events(events, min_duration=min_duration)
    out = []
    for item in chords_mod.analyze(events, min_notes=min_notes):
        chord = item.get("chord")
        if not chord or not chord.get("symbol"):
            continue
        start, end = float(item["start"]), float(item["end"])
        if end - start < min_seconds:
            continue
        entry = {
            "start": round(start, 2),
            "end": round(end, 2),
            "symbol": chord["symbol"],
        }
        voicing = item.get("voicing")
        if voicing:
            entry["positions"] = voicing["positions"]
            entry["shorthand"] = voicing["shorthand"]
        out.append(entry)
    return out


def detect_notes(note_events_path, *, min_duration=0.04):
    """Every transcribed note, lightly filtered — fills and runs included.

    Where :func:`detect_chords` keeps only sustained groupings, this keeps
    the single notes and quick slides *between* the chords — the licks.
    Sub-40ms events are attack transients even a fast hammer-on outlasts.
    """
    from . import notes as notes_mod

    if not note_events_path:
        return []
    out = []
    for e in notes_mod.read_note_events(note_events_path):
        if (e["end"] - e["start"]) < min_duration:
            continue
        entry = {"start": e["start"], "end": e["end"], "midi": e["midi"]}
        if e.get("velocity") is not None:
            entry["velocity"] = e["velocity"]
        out.append(entry)
    return out


_ROOT_RE = re.compile(r"^([A-G][#b]?)")


def _root(symbol):
    match = _ROOT_RE.match(symbol or "")
    return match.group(1) if match else symbol


def canonical_shapes(chords, *, symbols=None):
    """One fingering per chord symbol — the one a player would use.

    A common chord gets its textbook grip: the transcription's literal
    voicings are honest about the detected notes but not about the hand,
    and a chart of them looks wrong to anyone who plays. Chords without a
    standard grip fall back to the most frequently detected fingering.
    Returns ``[(symbol, shorthand, positions)…]`` sorted by symbol,
    optionally restricted to *symbols*.
    """
    from . import chords as chords_mod

    counts = Counter()
    sample = {}
    for c in chords or []:
        sym, short = c.get("symbol"), c.get("shorthand")
        if not sym or not short:
            continue
        if symbols is not None and sym not in symbols:
            continue
        counts[(sym, short)] += 1
        sample.setdefault((sym, short), c.get("positions"))
    best = {}
    for (sym, short), n in counts.items():
        if sym not in best or n > best[sym][1]:
            best[sym] = (short, n)
    out = []
    for sym, (short, _n) in best.items():
        textbook = chords_mod.textbook_shape(sym)
        if textbook:
            out.append((sym, chords_mod.shorthand(textbook), textbook))
        else:
            out.append((sym, short, sample[(sym, short)]))
    return sorted(out)


def progression_events(chords, sections):
    """Group named chords under the structure's sections, with time ranges.

    Returns ``[(label, span_start, span_end, [(symbol, t0, t1)…])…]``.
    Without *sections* everything lands under one ``None`` label. A run of
    chords on the same root collapses to that run's most frequent symbol
    spanning the whole run: a bar of strumming where the transcription
    flickers C · Csus2 · C5 is one C, not three chords — the flicker is
    pick attack, not harmony.
    """
    if not chords:
        return []
    spans = [
        (s["label"], float(s["start"]), float(s["end"]))
        for s in (sections or [])
    ] or [(None, 0.0, float("inf"))]

    grouped = []
    for label, start, end in spans:
        runs = []  # [(root, [symbols], run_start, run_end)…]
        for c in chords:
            when, sym = c.get("start"), c.get("symbol")
            if when is None or not sym:
                continue  # lick-style entries carry no timeline position
            t0, t1 = float(when), float(c.get("end") or when)
            if start <= t0 < end:
                root = _root(sym)
                if runs and runs[-1][0] == root:
                    runs[-1][1].append(sym)
                    runs[-1][3] = max(runs[-1][3], t1)
                else:
                    runs.append([root, [sym], t0, t1])
        events = [
            (Counter(run).most_common(1)[0][0], t0, t1)
            for _root_, run, t0, t1 in runs
        ]
        if events:
            span_end = end if end != float("inf") else events[-1][2]
            grouped.append((label, start, span_end, events))
    return grouped


def progression_by_section(chords, sections):
    """:func:`progression_events` reduced to just the symbol sequences."""
    return [
        (label, start, [sym for sym, _t0, _t1 in events])
        for label, start, _end, events in progression_events(chords, sections)
    ]


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

    chords_stage = result["stages"].get("chords", {})
    detected = chords_stage.get("chords") or []
    if detected:
        lines += ["## Chords as played", ""]
        if chords_stage.get("from_instrumental_stem"):
            lines.append("*Transcribed from the instrumental stem.*")
        else:
            lines.append(
                "*Transcribed from the full mix — the vocal can smear "
                "voicings; trust your ears over the exact extensions.*"
            )
        lines.append("")
        sections = (structure or {}).get("sections") if structure else None
        shown = set()
        for label, start, symbols in progression_by_section(detected, sections):
            shown.update(symbols)
            if label:
                lines.append(
                    "- **{}** ({}) — {}".format(
                        label, _clock(start), " · ".join(symbols)
                    )
                )
            else:
                lines.append("- {}".format(" · ".join(symbols)))
        shapes = canonical_shapes(detected, symbols=shown or None)
        if shapes:
            lines += [
                "",
                "Shapes: "
                + "  ".join(
                    "{} `{}`".format(sym, short)
                    for sym, short, _pos in shapes
                ),
            ]
        norm_file = result["stages"].get("normalize", {}).get("file")
        if norm_file:
            lines += [
                "",
                "To work out any phrase note-for-note (tab, scale, sheet "
                "music), trim tightly:",
                "",
                "```",
                "music-stack lick --input {} --start 0:24 --end 0:31".format(
                    norm_file
                ),
                "```",
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
