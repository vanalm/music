"""A self-contained HTML report — the closest thing this tool has to a UI.

``analyze`` writes ``report.html`` next to ``brief.md``. Double-click it and
the browser shows the song: an audio player wired to a clickable section
timeline with a live playhead, the lyric as sung, stems, chord shapes as SVG
boxes, and the questions.

Constraints, deliberately:

* **One file, zero dependencies.** Generated with the standard library — no
  frameworks, no CDN, no network requests. It works on an aeroplane and never
  breaks because a host moved.
* **The audio travels with the page when it can.** The player embeds a
  compact AAC preview as a data URI when ffmpeg is present and the result is
  small enough, so the file survives being mailed to a bandmate. Otherwise it
  degrades to a *relative path* into the project folder — and says so.
* **Sparse analysis → sparse page, never a broken one.** Each section renders
  from whatever the brief holds; a missing stage states how to get it.
"""

import base64
import html as _html
import os
import subprocess
import tempfile
from pathlib import Path

from . import audio as audio_mod
from . import notes as notes_mod
from .notes import note_name

#: Section label -> hue, so the timeline is scannable at a glance.
_SECTION_HUES = {
    "intro": 210, "verse": 150, "chorus": 345, "bridge": 45,
    "solo": 280, "inst": 280, "break": 25, "outro": 265,
}


def _esc(text):
    return _html.escape(str(text if text is not None else ""), quote=True)


#: Reference listening, not mixing — keeps a 4-minute song near 3 MB.
PREVIEW_BITRATE = "96k"

#: Cap on the embedded preview before base64 inflation (~4/3 in the page).
MAX_EMBED_BYTES = 12 * 1024 * 1024


def preview_audio(path, *, max_bytes=MAX_EMBED_BYTES):
    """Return ``(data_uri, note)`` for *path*, or ``(None, reason)``.

    Transcodes to AAC first: embedding a 24-bit WAV would produce a page
    hundreds of megabytes wide once base64 inflates it by a third.
    """
    path = Path(path)
    if not path.exists():
        return None, "audio file not found"
    ffmpeg = audio_mod.which("ffmpeg")
    if not ffmpeg:
        return None, "ffmpeg not installed, so no embedded preview"

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "preview.m4a"
        proc = subprocess.run(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error",
                "-nostdin", "-y", "-i", str(path), "-vn",
                "-c:a", "aac", "-b:a", PREVIEW_BITRATE, "-ar", "44100",
                str(out),
            ],
            capture_output=True,
        )
        if proc.returncode != 0 or not out.exists():
            return None, "ffmpeg could not make a preview"
        raw = out.read_bytes()

    if len(raw) > max_bytes:
        return None, "preview is {:.0f} MB, too large to embed".format(
            len(raw) / 1024 / 1024
        )
    return (
        "data:audio/mp4;base64," + base64.b64encode(raw).decode("ascii"),
        "embedded preview ({:.1f} MB)".format(len(raw) / 1024 / 1024),
    )


def _clock(seconds):
    seconds = int(float(seconds or 0))
    return "{:d}:{:02d}".format(seconds // 60, seconds % 60)


# -- chord boxes -----------------------------------------------------------


def chord_svg(positions, *, width=110, height=132):
    """Draw a chord box as inline SVG from voice_chord() positions.

    Strings are vertical lines (low E left), frets horizontal. Fretted notes
    are dots, open strings circles above the nut, unused strings an ``x``.
    """
    by_string = {p["string"]: p["fret"] for p in positions}
    fretted = [f for f in by_string.values() if f and f > 0]
    base = min(fretted) if fretted and min(fretted) > 1 else 1
    # Wide enough for the widest voicing — a detected shape can span more
    # than a textbook's five frets, and must draw rather than crash.
    n_frets = max(5, (max(fretted) - base + 1) if fretted else 5)

    left, top, right, bottom = 18, 26, width - 12, height - 10
    string_x = {
        s: left + (right - left) * (6 - s) / 5.0 for s in range(1, 7)
    }
    fret_y = [
        top + (bottom - top) * i / float(n_frets) for i in range(n_frets + 1)
    ]

    parts = [
        '<svg class="chordbox" viewBox="0 0 {w} {h}" '
        'xmlns="http://www.w3.org/2000/svg">'.format(w=width, h=height)
    ]
    # nut or base-fret label
    if base == 1:
        parts.append(
            '<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" class="nut"/>'.format(
                x1=left, x2=right, y=top
            )
        )
    else:
        parts.append(
            '<text x="{x}" y="{y}" class="basefret">{n}fr</text>'.format(
                x=right + 2, y=top + 12, n=base
            )
        )
    for y in fret_y:
        parts.append(
            '<line x1="{x1}" y1="{y:.1f}" x2="{x2}" y2="{y:.1f}" '
            'class="fret"/>'.format(x1=left, x2=right, y=y)
        )
    for s, x in string_x.items():
        parts.append(
            '<line x1="{x:.1f}" y1="{y1}" x2="{x:.1f}" y2="{y2}" '
            'class="string"/>'.format(x=x, y1=top, y2=bottom)
        )
    for s in range(6, 0, -1):
        x = string_x[s]
        fret = by_string.get(s)
        if fret is None:
            parts.append(
                '<text x="{x:.1f}" y="{y}" class="mark">x</text>'.format(
                    x=x, y=top - 8
                )
            )
        elif fret == 0:
            parts.append(
                '<circle cx="{x:.1f}" cy="{y}" r="4.5" class="open"/>'.format(
                    x=x, y=top - 11
                )
            )
        else:
            row = fret - base
            cy = (fret_y[row] + fret_y[row + 1]) / 2.0
            parts.append(
                '<circle cx="{x:.1f}" cy="{cy:.1f}" r="6.5" '
                'class="dot"/>'.format(x=x, cy=cy)
            )
    parts.append("</svg>")
    return "".join(parts)


def note_roll(events, start, end, *, width=1000, row=8):
    """A piano roll of every note in ``[start, end)`` — the licks included.

    Time runs left to right across the section, pitch bottom to top, one
    rectangle per transcribed note. This is the accuracy-first view: no
    string-assignment guessing, just what was detected, when, at what
    pitch. Hover a note for its name and time; the page script drives a
    playhead across it in sync with the audio.
    """
    span = max(float(end) - float(start), 0.001)
    notes = [
        e for e in events or []
        if float(e["start"]) < end and float(e["end"]) > start
    ]
    if not notes:
        return ""
    lo = min(n["midi"] for n in notes) - 1
    hi = max(n["midi"] for n in notes) + 1
    height = (hi - lo + 1) * row
    parts = [
        '<svg class="roll" viewBox="0 0 {w} {h}" width="100%" '
        'preserveAspectRatio="none" '
        'xmlns="http://www.w3.org/2000/svg">'.format(w=width, h=height)
    ]
    # Octave guide lines with a label at each C.
    for midi in range(lo, hi + 1):
        if midi % 12 != 0:
            continue
        y = (hi - midi) * row
        parts.append(
            '<line x1="0" y1="{y}" x2="{w}" y2="{y}" class="octave"/>'
            '<text x="4" y="{ty}" class="octlabel">{name}</text>'.format(
                y=y, w=width, ty=y - 2, name=note_name(midi)
            )
        )
    for n in notes:
        t0 = max(float(n["start"]), start)
        t1 = min(float(n["end"]), end)
        x = (t0 - start) / span * width
        w = max((t1 - t0) / span * width, 3.0)
        y = (hi - n["midi"]) * row
        velocity = n.get("velocity")
        opacity = 0.85
        if velocity is not None:
            opacity = 0.35 + 0.65 * max(0.0, min(float(velocity) / 127.0, 1.0))
        parts.append(
            '<rect class="nr" x="{x:.1f}" y="{y}" width="{w:.1f}" '
            'height="{h}" rx="2" opacity="{o:.2f}">'
            "<title>{name} · {t}s</title></rect>".format(
                x=x, y=y + 1, w=w, h=row - 2, o=opacity,
                name=_esc(note_name(n["midi"])),
                t=round(float(n["start"]), 1),
            )
        )
    parts.append("</svg>")
    return "".join(parts)


def name_columns(events, *, window=0.08):
    """Group notes into time columns for the stacked-names row.

    Notes starting within *window* of the column's first onset stack into
    one column (a strummed chord reads vertically); columns run left to
    right in playback order, mirroring the roll above them.
    """
    cols = []
    for e in sorted(events or [], key=lambda x: (float(x["start"]), x["midi"])):
        start = float(e["start"])
        if cols and start - cols[-1]["start"] <= window:
            cols[-1]["midis"].append(e["midi"])
            cols[-1]["end"] = max(cols[-1]["end"], float(e["end"]))
        else:
            cols.append(
                {"start": start, "end": float(e["end"]), "midis": [e["midi"]]}
            )
    return cols


def _names_row(events, start, end):
    """The hover-free view: every note name, placed at its moment.

    Columns sit at the same horizontal fraction as their notes in the roll
    above, so the eye can drop straight down. They render tiny; the page
    script grows the column under the playhead (and its neighbours) as the
    line passes through.
    """
    cols = name_columns(events)
    if not cols:
        return ""
    span = max(float(end) - float(start), 0.001)
    spans = []
    for col in cols:
        names = "".join(
            "<i>{}</i>".format(_esc(note_name(m, flats=True)))
            for m in sorted(col["midis"], reverse=True)
        )
        left = max(0.0, min((col["start"] - start) / span * 100.0, 100.0))
        spans.append(
            '<span class="ncol" style="left:{left:.2f}%" '
            'data-start="{t0}" data-end="{t1}">{names}</span>'.format(
                left=left, t0=round(col["start"], 2),
                t1=round(col["end"], 2), names=names,
            )
        )
    return '<div class="names namesline">{}</div>'.format("".join(spans))


#: Pitch class -> (letter index C=0..B=6, accidental) using flat spellings,
#: matching FLAT note names.
_PC_DIATONIC = {
    0: (0, ""), 1: (1, "♭"), 2: (1, ""), 3: (2, "♭"), 4: (2, ""),
    5: (3, ""), 6: (4, "♭"), 7: (4, ""), 8: (5, "♭"), 9: (5, ""),
    10: (6, "♭"), 11: (6, ""),
}


def _diatonic(midi):
    letter, accidental = _PC_DIATONIC[midi % 12]
    return (midi // 12 - 1) * 7 + letter, accidental


def staff_svg(events, start, end, *, width=1000):
    """A grand-staff pitch view: treble and bass clefs, time proportional
    left to right, ledger lines and flats where needed.

    Low notes sit on the bass staff instead of dangling from the treble on
    a tower of ledger lines; middle C takes the conventional single ledger
    between the staves. Deliberately unmetered — no stems, beams, or bar
    lines — because the transcription carries pitch and time, not note
    values. The MusicXML export remains the route to engraved rhythm.
    """
    span = max(float(end) - float(start), 0.001)
    notes = [
        e for e in events or []
        if float(e["start"]) < end and float(e["end"]) > start
    ]
    if not notes:
        return ""
    step, gutter = 4, 44
    treble_lines = (30, 32, 34, 36, 38)  # E4 G4 B4 D5 F5
    bass_lines = (18, 20, 22, 24, 26)    # G2 B2 D3 F3 A3
    diatonics = [_diatonic(n["midi"])[0] for n in notes]
    d_hi = max(38, max(diatonics)) + 2
    d_lo = min(18, min(diatonics)) - 2

    def y(d):
        return 8 + (d_hi - d) * step

    height = y(d_lo) + 8
    parts = [
        '<svg class="staff" viewBox="0 0 {w} {h}" width="100%" '
        'xmlns="http://www.w3.org/2000/svg">'.format(w=width, h=height)
    ]
    for d in treble_lines + bass_lines:
        parts.append(
            '<line x1="8" y1="{y}" x2="{w}" y2="{y}" class="sline"/>'.format(
                y=y(d), w=width
            )
        )
    # The connecting barline and both clefs.
    parts.append(
        '<line x1="8" y1="{t}" x2="8" y2="{b}" class="sline"/>'.format(
            t=y(38), b=y(18)
        )
    )
    parts.append(
        '<text x="10" y="{y}" class="clef">\U0001d11e</text>'.format(
            y=y(30) + 2
        )
    )
    parts.append(
        '<text x="12" y="{y}" class="clef bclef">\U0001d122</text>'.format(
            y=y(22) + 1
        )
    )
    for n in notes:
        d, accidental = _diatonic(n["midi"])
        x = gutter + (max(float(n["start"]), start) - start) / span \
            * (width - gutter - 10)
        ny = y(d)
        on_treble = d >= 29
        if on_treble:
            if d < 30:  # middle C: one ledger below the treble staff
                parts.append(
                    '<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" '
                    'class="ledger"/>'.format(x0=x - 8, x1=x + 8, y=y(28))
                )
            for ledger in range(40, d + 1, 2):
                parts.append(
                    '<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" '
                    'class="ledger"/>'.format(x0=x - 8, x1=x + 8, y=y(ledger))
                )
        else:
            for ledger in range(28, d - 1, -2):
                if ledger > 26:  # between the staves (middle C region)
                    parts.append(
                        '<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" '
                        'class="ledger"/>'.format(
                            x0=x - 8, x1=x + 8, y=y(ledger)
                        )
                    )
            for ledger in range(16, d - 1, -2):
                parts.append(
                    '<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" '
                    'class="ledger"/>'.format(x0=x - 8, x1=x + 8, y=y(ledger))
                )
        if accidental:
            parts.append(
                '<text x="{x}" y="{y}" class="acc">{a}</text>'.format(
                    x=x - 13, y=ny + 3.5, a=accidental
                )
            )
        parts.append(
            '<ellipse class="sn" cx="{x:.1f}" cy="{y}" rx="4.6" ry="3.4">'
            "<title>{name} · {t}s</title></ellipse>".format(
                x=x, y=ny, name=_esc(note_name(n["midi"], flats=True)),
                t=round(float(n["start"]), 1),
            )
        )
    parts.append("</svg>")
    return "".join(parts)


# -- page ------------------------------------------------------------------


def build(result, *, audio_path=None, chords=None):
    """Render an ``analyze`` result (the ``brief.json`` shape) as one page."""
    from . import brief as brief_mod

    stages = result.get("stages") or {}
    structure = (stages.get("structure") or {}).get("summary") or {}
    lyrics = stages.get("lyrics") or {}
    stems = stages.get("stems") or {}
    norm = (stages.get("normalize") or {}).get("summary") or {}
    sections = structure.get("sections") or []
    duration = structure.get("duration_seconds") or norm.get("duration_seconds") or 0

    # -- audio ------------------------------------------------------------
    if audio_path:
        data_uri, note = preview_audio(audio_path)
        if data_uri:
            audio_html = (
                '<audio id="player" controls preload="metadata" '
                'src="{}"></audio>'.format(data_uri)
            )
        else:
            # Fall back to a relative path: report.html sits in the project
            # dir, the normalized WAV one level down. If the exact relative
            # path cannot be derived, the bare filename is still the best
            # guess -- browsers resolve it against the page, and a wrong
            # guess degrades to a silent player, not a broken page.
            audio_src = os.path.basename(str(audio_path))
            project = result.get("project")
            if project:
                try:
                    audio_src = str(Path(audio_path).relative_to(project))
                except ValueError:
                    pass
            audio_html = (
                '<audio id="player" controls preload="metadata" src="{src}">'
                '</audio>'
                '<p class="note">Audio is not embedded ({why}); playback '
                'needs this file to stay next to its project folder.</p>'
            ).format(src=_esc(audio_src), why=_esc(note))
    else:
        audio_html = '<p class="note">No audio available for playback.</p>'

    # -- timeline ---------------------------------------------------------
    if sections and duration:
        seg_parts = []
        for s in sections:
            width = 100.0 * float(s["seconds"]) / float(duration)
            hue = _SECTION_HUES.get(str(s["label"]).lower(), 200)
            seg_parts.append(
                '<div class="seg" data-start="{start}" '
                'style="width:{w:.3f}%;--hue:{h}" '
                'title="{label} · {t0}–{t1}"><span>{label}</span></div>'.format(
                    start=s["start"], w=width, h=hue, label=_esc(s["label"]),
                    t0=_clock(s["start"]), t1=_clock(s["end"]),
                )
            )
        timeline_html = (
            '<div class="timeline" id="timeline">{segs}'
            '<div id="playhead"></div></div>'.format(segs="".join(seg_parts))
        )
    else:
        timeline_html = (
            '<p class="note">No structure analysis yet — install allin1 '
            "(<code>music-stack local doctor</code> has the steps) and re-run "
            "<code>music-stack analyze</code>.</p>"
            '<div style="display:none" id="playhead"></div>'
        )

    # -- facts ------------------------------------------------------------
    facts = []
    if structure.get("bpm"):
        facts.append("<b>{}</b> BPM".format(_esc(structure["bpm"])))
    if duration:
        facts.append("<b>{}</b>".format(_clock(duration)))
    if norm.get("codec"):
        facts.append("{} · {} Hz".format(_esc(norm["codec"]),
                                         _esc(norm.get("sample_rate", "?"))))
    facts_html = " &nbsp;·&nbsp; ".join(facts)

    missing = structure.get("missing") or []
    missing_html = ""
    if missing:
        chips = "".join('<span class="chip">{}</span>'.format(_esc(m))
                        for m in missing)
        missing_html = '<p class="missing">Not present yet: {}</p>'.format(chips)

    # -- lyrics -----------------------------------------------------------
    lyrics_html = ""
    if lyrics.get("text"):
        provenance = (
            "transcribed from the isolated vocal stem"
            if lyrics.get("from_isolated_vocal")
            else "transcribed from the full mix — expect errors where "
                 "instruments mask the vocal"
        )
        lyrics_html = (
            "<h2>Lyrics as sung</h2>"
            '<p class="note">{}</p>'
            '<div class="card-block"><pre class="lyrics">{}</pre>'
            "</div>".format(_esc(provenance), _esc(lyrics["text"]))
        )

    # -- stems ------------------------------------------------------------
    stems_html = ""
    stem_files = stems.get("files") or []
    if stem_files:
        items = "".join(
            '<li><a href="{name}">{name}</a></li>'.format(
                name=_esc(Path(f).name)
            )
            for f in stem_files
        )
        stems_html = '<h2>Stems</h2><ul class="stems">{}</ul>'.format(items)

    # -- chords -----------------------------------------------------------
    if chords is None:
        chords = (stages.get("chords") or {}).get("chords")
    chords_html = ""
    viewbar_html = ""
    if chords:
        from . import chords as chords_mod

        canon = {
            sym: (short, positions)
            for sym, short, positions in brief_mod.canonical_shapes(chords)
        }
        panels = []
        shown = set()
        norm_file = (stages.get("normalize") or {}).get("file")
        all_notes = (stages.get("chords") or {}).get("notes") or []
        for label, s_start, s_end, events in brief_mod.progression_events(
            chords, sections
        ):
            symbols = [sym for sym, _t0, _t1 in events]
            shown.update(symbols)
            # Chips: one per chord as played — click to hear it, and the
            # one currently sounding lights up during playback.
            chips = "".join(
                '<span class="chip" data-start="{t0}" data-end="{t1}">'
                "{sym}</span>".format(t0=t0, t1=t1, sym=_esc(sym))
                for sym, t0, t1 in events
            )
            sec_events = [
                e for e in all_notes
                if float(e["start"]) < s_end and float(e["end"]) > s_start
            ]

            # View 1 — piano roll with the note names aligned beneath it.
            roll = note_roll(sec_events, s_start, s_end)
            roll_view = '<p class="note">No notes transcribed here.</p>'
            if roll:
                roll_view = (
                    '<div class="rollwrap" data-start="{t0}" '
                    'data-end="{t1}">{roll}'
                    '<div class="roll-line"></div></div>{names}'.format(
                        t0=s_start, t1=s_end, roll=roll,
                        names=_names_row(sec_events, s_start, s_end),
                    )
                )

            # View 2 — every note as guitar tab, hand kept in position. The
            # data-times list lets the script walk a playhead through the
            # text, one monospace column per note.
            tab_view = '<p class="note">No notes transcribed here.</p>'
            if sec_events:
                ordered = sorted(
                    sec_events, key=lambda e: (float(e["start"]), e["midi"])
                )
                positioned = notes_mod.choose_positions(
                    ordered, strings=(1, 2, 3, 4, 5, 6)
                )
                times = ",".join(
                    str(round(float(e["start"]), 2)) for e in ordered
                )
                tab_view = (
                    '<div class="tabwrap" data-start="{t0}" data-end="{t1}" '
                    'data-times="{times}" data-lead="2" data-colw="4">'
                    '<div class="tabinner"><pre class="tab">{tab}</pre>'
                    '<div class="roll-line tab-line"></div></div>'
                    "</div>".format(
                        t0=s_start, t1=s_end, times=times,
                        tab=_esc(notes_mod.render_tab(
                            positioned, strings=(1, 2, 3, 4, 5, 6), width=3
                        )),
                    )
                )

            # View 3 — treble-staff pitch view.
            staff = staff_svg(sec_events, s_start, s_end)
            staff_view = '<p class="note">No notes transcribed here.</p>'
            if staff:
                staff_view = (
                    '<div class="rollwrap staffwrap" data-start="{t0}" '
                    'data-end="{t1}">{staff}'
                    '<div class="roll-line"></div></div>'.format(
                        t0=s_start, t1=s_end, staff=staff
                    )
                )

            # View 4 — the chords: chips plus the textbook-grip tab chart,
            # with the playhead walking chord to chord.
            chord_tab = chords_mod.render_chord_tab(
                [
                    {"voicing": {"positions": canon[sym][1]}}
                    if canon.get(sym) and canon[sym][1] else {"voicing": None}
                    for sym in symbols
                ]
            )
            chord_times = ",".join(
                str(round(t0, 2)) for _sym, t0, _t1 in events
            )
            chart_view = (
                '<div class="chips">{chips}</div>'
                '<div class="tabwrap" data-start="{t0}" data-end="{t1}" '
                'data-times="{times}" data-lead="2" data-colw="7">'
                '<div class="tabinner"><pre class="tab">{tab}</pre>'
                '<div class="roll-line tab-line"></div></div></div>'.format(
                    chips=chips, t0=s_start, t1=s_end, times=chord_times,
                    tab=_esc(chord_tab),
                )
            )

            lick = ""
            if norm_file:
                lick = (
                    '<div class="lickrow"><code class="lick">music-stack '
                    "lick --input {} --start {} --end {}</code>"
                    '<button class="copy" type="button">copy</button>'
                    "</div>".format(
                        _esc(norm_file), _clock(s_start), _clock(s_end),
                    )
                )
            hue = _SECTION_HUES.get(str(label or "").lower(), 210)
            panels.append(
                '<details class="panel" data-start="{t0}" data-end="{t1}" '
                'open><summary><span class="seclabel" style="--hue:{hue}">'
                "{label}</span>"
                '<span class="range">{c0}–{c1}</span>'
                '<span class="prog-mini">{mini}</span></summary>'
                '<div class="views">'
                '<div class="view active" data-view="roll">{roll}</div>'
                '<div class="view" data-view="gtab">{gtab}</div>'
                '<div class="view" data-view="staff">{staff}</div>'
                '<div class="view" data-view="chart">{chart}</div>'
                "</div>"
                "{lick}</details>".format(
                    t0=s_start, t1=s_end, hue=hue,
                    label=_esc(label or "all"),
                    c0=_clock(s_start), c1=_clock(s_end),
                    mini=_esc(" · ".join(symbols[:8])
                              + (" …" if len(symbols) > 8 else "")),
                    roll=roll_view, gtab=tab_view, staff=staff_view,
                    chart=chart_view, lick=lick,
                )
            )
        prog_html = ""
        if panels:
            prog_html = '<div class="progression">{}</div>'.format(
                "".join(panels)
            )
            # One switcher drives every section; it lives in the sticky
            # player bar so it is always in reach.
            viewbar_html = (
                '<div class="vtabs">'
                '<button type="button" class="vtab active" '
                'data-view="roll">Piano roll</button>'
                '<button type="button" class="vtab" data-view="gtab">'
                "Guitar tab</button>"
                '<button type="button" class="vtab" data-view="staff">'
                "Sheet music</button>"
                '<button type="button" class="vtab" data-view="chart">'
                "Chord chart</button>"
                "</div>"
            )
        # One box per chord, the most frequently detected fingering — a
        # hand learning the song wants one shape, not every strum variant.
        cards = []
        for sym in sorted(shown or canon):
            short, positions = canon.get(sym, (None, None))
            if not positions:
                continue
            cards.append(
                '<figure class="card">{svg}<figcaption>{sym}'
                "<small>{short}</small></figcaption></figure>".format(
                    svg=chord_svg(positions),
                    sym=_esc(sym),
                    short=_esc(short),
                )
            )
        if cards or prog_html:
            chords_html = (
                "<h2>Play along</h2>"
                '<p class="note">Every transcribed note, section by '
                "section — switch each panel between piano roll, guitar "
                "tab, sheet music, and the chord chart. Click anywhere in "
                "a roll or staff to hear that moment.</p>{prog}"
                "<h3>Chord shapes</h3><div class=\"cards\">{cards}</div>"
            ).format(prog=prog_html, cards="".join(cards))

    # -- questions --------------------------------------------------------
    questions_html = "".join(
        "<li>{}</li>".format(_esc(q)) for q in brief_mod.questions(result)
    )

    skipped = result.get("skipped") or []
    skipped_html = ""
    if skipped:
        skipped_html = (
            '<p class="note">Stages skipped (tool not installed): {}. Run '
            "<code>music-stack local doctor</code>.</p>".format(
                _esc(", ".join(skipped))
            )
        )

    return _TEMPLATE.format(
        title=_esc(result.get("title", "Untitled")),
        facts=facts_html,
        audio=audio_html,
        timeline=timeline_html,
        viewbar=viewbar_html,
        arrangement=_esc(structure.get("arrangement") or ""),
        missing=missing_html,
        lyrics=lyrics_html,
        stems=stems_html,
        chords=chords_html,
        questions=questions_html,
        skipped=skipped_html,
    )


def write(result, project_dir, *, audio_path=None, chords=None):
    """Write ``report.html`` into *project_dir*; returns its path."""
    project_dir = Path(project_dir)
    out = project_dir / "report.html"
    out.write_text(
        build(result, audio_path=audio_path, chords=chords), encoding="utf-8"
    )
    return out


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  /* A deliberately light, editorial surface: white cards on a warm gray
     page, one indigo accent, hairline borders instead of heavy shadows. */
  :root {{
    --bg: #f6f7f9; --card: #ffffff; --fg: #16181d; --muted: #667085;
    --line: #e4e7ec; --accent: #4f46e5; --accent-soft: #eef0fe;
    --panel: #f2f4f7;
  }}
  * {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{
    font: 15px/1.6 -apple-system, BlinkMacSystemFont, "SF Pro Text",
      Inter, "Segoe UI", Roboto, sans-serif;
    margin: 0; background: var(--bg); color: var(--fg);
    -webkit-font-smoothing: antialiased;
  }}
  main {{ max-width: 54rem; margin: 0 auto; padding: 1.4rem 1.2rem 4rem; }}
  h1 {{ font-size: 1.55rem; letter-spacing: -.02em; margin: .4rem 0 .1rem; }}
  h2 {{ font-size: .8rem; letter-spacing: .09em; text-transform: uppercase;
        color: var(--muted); margin: 2.6rem 0 .8rem; }}
  h3 {{ font-size: .8rem; letter-spacing: .09em; text-transform: uppercase;
        color: var(--muted); margin: 2rem 0 .8rem; }}
  .facts {{ color: var(--muted); font-size: .88rem; margin-bottom: 1rem; }}
  .facts b {{ color: var(--fg); }}

  .playerbar {{
    position: sticky; top: 0; z-index: 10; background: var(--card);
    border: 1px solid var(--line); border-radius: 14px;
    padding: .8rem 1rem .9rem; margin: 1rem 0 1.6rem;
    box-shadow: 0 1px 2px rgb(16 24 40 / .04),
                0 8px 24px -18px rgb(16 24 40 / .25);
  }}
  audio {{ width: 100%; height: 40px; }}
  .keys {{ color: var(--muted); font-size: .75rem; margin-top: .45rem; }}
  .keys kbd {{
    border: 1px solid var(--line); border-bottom-width: 2px;
    border-radius: 5px; padding: 0 .35rem; font: inherit;
    background: var(--panel);
  }}

  .timeline {{
    position: relative; display: flex; height: 2.6rem; margin-top: .7rem;
    border-radius: 9px; overflow: hidden; cursor: pointer;
  }}
  .seg {{
    display: flex; align-items: center; justify-content: center;
    min-width: 1.4rem; font-size: .68rem; font-weight: 650; color: #fff;
    background: hsl(var(--hue,210) 48% 52%);
    border-right: 1px solid rgb(255 255 255 / .4);
  }}
  .seg:hover {{ filter: brightness(1.12); }}
  .seg span {{ overflow: hidden; text-overflow: ellipsis;
               white-space: nowrap; padding: 0 .3rem; }}
  #playhead {{
    position: absolute; top: 0; bottom: 0; left: 0; width: 2px;
    background: #fff; box-shadow: 0 0 0 1px rgb(16 24 40 / .35);
    pointer-events: none; transition: left .2s linear;
  }}
  .arrangement {{ color: var(--muted); font-size: .82rem; margin-top: .6rem; }}
  .missing {{ font-size: .85rem; color: var(--muted); margin-top: .3rem; }}
  .missing .chip {{ background: #fef3f2; color: #b42318;
    border: 1px solid #fecdca; }}

  .card-block {{
    background: var(--card); border: 1px solid var(--line);
    border-radius: 14px; padding: 1.1rem 1.3rem;
  }}
  .lyrics {{ white-space: pre-wrap; font-size: .92rem; column-gap: 2.4rem;
    margin: 0; font-family: inherit; }}
  @media (min-width: 660px) {{ .lyrics {{ columns: 2; }} }}
  .note {{ font-size: .84rem; color: var(--muted); }}
  .stems {{ columns: 2; padding-left: 1.2rem; margin: 0; }}
  .stems a {{ color: var(--accent); text-decoration: none; }}
  .stems a:hover {{ text-decoration: underline; }}

  .progression .panel {{
    background: var(--card); border: 1px solid var(--line);
    border-radius: 14px; margin: .8rem 0; padding: .9rem 1.1rem;
    transition: border-color .15s, box-shadow .15s;
  }}
  .progression .panel.now {{
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-soft);
  }}
  .progression summary {{
    cursor: pointer; display: flex; align-items: baseline; gap: .6rem;
    list-style: none; flex-wrap: wrap;
  }}
  .progression summary::-webkit-details-marker {{ display: none; }}
  .seclabel {{
    font-size: .72rem; font-weight: 700; letter-spacing: .04em;
    text-transform: uppercase; color: #fff; padding: .12rem .6rem;
    border-radius: 999px; background: hsl(var(--hue,210) 48% 52%);
  }}
  .range {{ color: var(--muted); font-size: .8rem;
    font-variant-numeric: tabular-nums; }}
  .prog-mini {{ color: var(--muted); font-size: .8rem; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }}

  .chips {{ margin: .7rem 0 .5rem; display: flex; flex-wrap: wrap;
    gap: .3rem; }}
  .chip {{
    padding: .12rem .6rem; border-radius: 999px; cursor: pointer;
    background: var(--panel); border: 1px solid var(--line);
    font-size: .8rem; font-weight: 600; transition: all .12s;
  }}
  .chip:hover {{ border-color: var(--accent); color: var(--accent); }}
  .chip.now {{ background: var(--accent); border-color: var(--accent);
    color: #fff; }}

  .rollwrap {{ position: relative; margin: .6rem 0; cursor: crosshair;
    border: 1px solid var(--line); border-radius: 9px; overflow: hidden;
    background: linear-gradient(180deg, #fcfcfd, #f8f9fb); }}
  .roll {{ display: block; }}
  .roll .octave {{ stroke: var(--line); stroke-width: 1; }}
  .roll .octlabel {{ fill: var(--muted); font: 600 9px sans-serif; }}
  .roll .nr {{ fill: var(--accent); }}
  .roll .nr:hover {{ fill: #16181d; }}
  .roll-line {{
    position: absolute; top: 0; bottom: 0; left: 0; width: 1.5px;
    background: #e11d48; display: none; pointer-events: none;
  }}

  .tophead {{ display: flex; align-items: center; gap: 1rem;
    justify-content: space-between; }}
  .infobtn {{ width: 1.7rem; height: 1.7rem; border-radius: 50%;
    border: 1px solid var(--line); background: var(--card);
    color: var(--muted); font: italic 700 .9rem Georgia, serif;
    cursor: pointer; flex: none; }}
  .infobtn:hover {{ border-color: var(--accent); color: var(--accent); }}
  .infocard {{ margin: .4rem 0 1rem; font-size: .85rem; }}
  .infocard p {{ margin: .45rem 0; }}
  .views {{ margin-top: .7rem; }}
  .vtabs {{ display: inline-flex; gap: 2px; background: var(--panel);
    border: 1px solid var(--line); border-radius: 9px; padding: 2px;
    margin-top: .7rem; }}
  .vtab {{ border: 0; background: transparent; padding: .28rem .75rem;
    border-radius: 7px; font: inherit; font-size: .78rem;
    color: var(--muted); cursor: pointer; }}
  .vtab:hover {{ color: var(--fg); }}
  .vtab.active {{ background: var(--card); color: var(--fg);
    font-weight: 600; box-shadow: 0 1px 2px rgb(16 24 40 / .1); }}
  .view {{ display: none; margin-top: .6rem; }}
  .view.active {{ display: block; }}

  .namesline {{ position: relative; height: 3.4rem; margin-top: .15rem; }}
  .ncol {{ position: absolute; top: 0; transform: translateX(-50%);
    display: inline-flex; flex-direction: column; align-items: center;
    padding: 0 .1rem; border-radius: 4px;
    font: 600 .48rem/1.25 ui-monospace, "SF Mono", Menlo, monospace;
    color: var(--muted); opacity: .55; cursor: pointer;
    transition: font-size .12s, opacity .12s; }}
  .ncol i {{ font-style: normal; }}
  .ncol:hover {{ color: var(--accent); opacity: 1; z-index: 4; }}
  .ncol.near {{ font-size: .6rem; opacity: .9; color: var(--fg);
    z-index: 2; }}
  .ncol.now {{ font-size: .72rem; opacity: 1; background: var(--accent);
    color: #fff; z-index: 3; }}

  .tabwrap {{ overflow-x: auto; border: 1px solid var(--line);
    border-radius: 9px; background: var(--panel); }}
  .tabinner {{ position: relative; display: inline-block;
    min-width: 100%; }}
  .tabwrap .tab {{ margin: 0; border: 0; background: transparent;
    overflow: visible; }}
  .tab-line {{ display: none; margin-left: .9rem; }}

  .staffwrap {{ cursor: crosshair; background: #fff; }}
  .staff {{ display: block; }}
  .staff .sline {{ stroke: #98a2b3; stroke-width: 1; }}
  .staff .ledger {{ stroke: #98a2b3; stroke-width: 1; }}
  .staff .clef {{ font-size: 40px; fill: var(--fg); }}
  .staff .bclef {{ font-size: 30px; }}
  .staff .acc {{ font-size: 10px; fill: var(--fg); }}
  .staff .sn {{ fill: var(--accent); }}
  .staff .sn:hover {{ fill: #16181d; }}

  .tabfold {{ margin: .5rem 0 0; }}
  .tabfold summary {{ cursor: pointer; color: var(--muted);
    font-size: .8rem; }}
  .tab, .tab-line {{
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: .78rem;
  }}
  .tab {{ overflow-x: auto; line-height: 1.4;
    margin: .5rem 0 0; background: var(--panel); padding: .7rem .9rem;
    border-radius: 9px; }}
  .lickrow {{ display: flex; gap: .5rem; align-items: center;
    margin-top: .6rem; }}
  .lickrow .lick {{ flex: 1; min-width: 0; overflow-x: auto;
    white-space: nowrap; font-size: .74rem; color: var(--muted); }}
  .copy {{
    border: 1px solid var(--line); background: var(--card);
    border-radius: 7px; padding: .15rem .6rem; font-size: .74rem;
    cursor: pointer; color: var(--muted);
  }}
  .copy:hover {{ border-color: var(--accent); color: var(--accent); }}

  .cards {{ display: grid; gap: .8rem;
    grid-template-columns: repeat(auto-fill, minmax(112px, 1fr)); }}
  .card {{
    margin: 0; padding: .7rem .4rem .5rem; background: var(--card);
    border: 1px solid var(--line); border-radius: 12px; text-align: center;
  }}
  .card figcaption {{ font-weight: 700; font-size: .92rem; }}
  .card small {{ display: block; font-weight: 500; color: var(--muted);
    font-size: .72rem; margin-top: .1rem; }}
  .chordbox {{ width: 100%; max-width: 110px; height: auto; }}
  .chordbox .fret, .chordbox .string {{ stroke: #d0d5dd; stroke-width: 1; }}
  .chordbox .nut {{ stroke: var(--fg); stroke-width: 3; }}
  .chordbox .dot {{ fill: var(--fg); }}
  .chordbox .open {{ fill: none; stroke: var(--fg); stroke-width: 1.5; }}
  .chordbox .mark, .chordbox .basefret {{
    fill: var(--muted); font: 600 11px sans-serif; text-anchor: middle;
  }}
  .chordbox .basefret {{ text-anchor: start; }}
  ul {{ padding-left: 1.2rem; }}
  li {{ margin: .45rem 0; }}
  code {{ background: var(--panel); padding: .1rem .35rem;
          border-radius: 5px; font-size: .85em; }}
</style>
</head>
<body>
<main>
<header class="tophead">
<h1>{title}</h1>
<button id="infobtn" class="infobtn" type="button"
  aria-label="About this page">i</button>
</header>
<div class="facts">{facts}</div>
<div id="infocard" class="card-block infocard" hidden>
<p><b>How this was made</b> — analyzed on your machine by
<code>music-stack</code>: ffmpeg (audio prep) · Demucs htdemucs (stem
separation) · allin1 + madmom (tempo &amp; sections) · mlx-whisper
(lyrics) · basic-pitch (note transcription). The page itself is
dependency-free HTML/SVG with the audio embedded — mail it to anyone.</p>
<p><b>Using it</b> — <kbd>space</kbd> play/pause · <kbd>←</kbd>
<kbd>→</kbd> scrub · click the timeline, a chord chip, a note name, or
anywhere in a roll or staff to jump there · the toggle switches every
section between Piano roll, Guitar tab, Sheet music, and Chord chart ·
each section's <code>music-stack lick</code> command re-transcribes just
that span for note-perfect tab, scale, and sheet music.</p>
<p><b>Accuracy</b> — transcription is machine listening on a full mix:
trust the progression and timing, and verify oddball chords or fast licks
with <code>lick</code> on a tight time window.</p>
</div>
<div class="playerbar">
{audio}
{timeline}
{viewbar}
<div class="keys"><kbd>space</kbd> play / pause &nbsp; <kbd>←</kbd>
<kbd>→</kbd> scrub 1s &nbsp; click a section, chord, or note to jump
there</div>
</div>
<div class="arrangement">{arrangement}</div>
{missing}
{chords}
{lyrics}
{stems}
<h2>To finish this</h2>
<ul>{questions}</ul>
{skipped}
</main>
<script>
  (function () {{
    var player = document.getElementById("player");
    var playhead = document.getElementById("playhead");
    var timeline = document.getElementById("timeline");
    var lastPanel = null;
    var vbuttons = document.querySelectorAll(".vtabs .vtab");
    vbuttons.forEach(function (btn) {{
      btn.addEventListener("click", function () {{
        vbuttons.forEach(function (b) {{
          b.classList.toggle("active", b === btn);
        }});
        document.querySelectorAll(".view").forEach(function (pane) {{
          pane.classList.toggle(
            "active", pane.dataset.view === btn.dataset.view
          );
        }});
      }});
    }});
    var infoBtn = document.getElementById("infobtn");
    var infoCard = document.getElementById("infocard");
    if (infoBtn && infoCard) {{
      infoBtn.addEventListener("click", function () {{
        infoCard.hidden = !infoCard.hidden;
      }});
    }}
    if (!player) return;
    document.querySelectorAll(
      ".seg[data-start], .chip[data-start], .ncol[data-start]"
    ).forEach(function (el) {{
      el.addEventListener("click", function () {{
        player.currentTime = parseFloat(el.dataset.start);
        player.play();
      }});
    }});
    var timed = document.querySelectorAll(
      ".panel[data-start], .chip[data-start]"
    );
    var nameslines = [];
    document.querySelectorAll(".namesline").forEach(function (row) {{
      var panel = row.closest(".panel");
      nameslines.push({{
        cols: Array.prototype.slice.call(row.querySelectorAll(".ncol")),
        t0: panel ? parseFloat(panel.dataset.start) : 0,
        t1: panel ? parseFloat(panel.dataset.end) : Infinity
      }});
    }});
    var tabwraps = [];
    document.querySelectorAll(".tabwrap[data-times]").forEach(function (w) {{
      tabwraps.push({{
        el: w,
        times: (w.dataset.times || "").split(",").map(parseFloat)
          .filter(isFinite),
        line: w.querySelector(".tab-line"),
        t0: parseFloat(w.dataset.start),
        t1: parseFloat(w.dataset.end),
        lead: parseFloat(w.dataset.lead || 2),
        colw: parseFloat(w.dataset.colw || 4)
      }});
    }});
    var rolls = document.querySelectorAll(".rollwrap[data-start]");
    rolls.forEach(function (wrap) {{
      wrap.addEventListener("click", function (e) {{
        var rect = wrap.getBoundingClientRect();
        var frac = (e.clientX - rect.left) / rect.width;
        var t0 = parseFloat(wrap.dataset.start);
        var t1 = parseFloat(wrap.dataset.end);
        player.currentTime = t0 + frac * (t1 - t0);
        player.play();
      }});
    }});
    player.addEventListener("timeupdate", function () {{
      if (playhead && timeline && player.duration) {{
        playhead.style.left =
          (100 * player.currentTime / player.duration) + "%";
      }}
      var t = player.currentTime;
      timed.forEach(function (el) {{
        var on = t >= parseFloat(el.dataset.start) &&
                 t < parseFloat(el.dataset.end);
        el.classList.toggle("now", on);
      }});
      // The line flows on into the next section: follow it down the page.
      if (!player.paused) {{
        var nowPanel = document.querySelector(".panel.now");
        if (nowPanel && nowPanel !== lastPanel) {{
          lastPanel = nowPanel;
          nowPanel.scrollIntoView({{behavior: "smooth", block: "nearest"}});
        }}
      }}
      rolls.forEach(function (wrap) {{
        var t0 = parseFloat(wrap.dataset.start);
        var t1 = parseFloat(wrap.dataset.end);
        var line = wrap.querySelector(".roll-line");
        if (!line) return;
        if (t >= t0 && t < t1) {{
          line.style.display = "block";
          line.style.left = (100 * (t - t0) / (t1 - t0)) + "%";
        }} else {{
          line.style.display = "none";
        }}
      }});
      nameslines.forEach(function (row) {{
        var active = -1;
        if (t >= row.t0 && t < row.t1) {{
          for (var i = 0; i < row.cols.length; i++) {{
            if (parseFloat(row.cols[i].dataset.start) <= t) active = i;
            else break;
          }}
        }}
        row.cols.forEach(function (col, i) {{
          col.classList.toggle("now", i === active);
          col.classList.toggle("near",
            active >= 0 && (i === active - 1 || i === active + 1));
        }});
      }});
      tabwraps.forEach(function (w) {{
        if (!w.line) return;
        if (t < w.t0 || t >= w.t1 || !w.times.length) {{
          w.line.style.display = "none";
          return;
        }}
        var idx = -1;
        for (var i = 0; i < w.times.length; i++) {{
          if (w.times[i] <= t) idx = i; else break;
        }}
        if (idx < 0) {{ w.line.style.display = "none"; return; }}
        w.line.style.display = "block";
        w.line.style.left = (w.lead + idx * w.colw + w.colw / 2) + "ch";
        w.el.scrollLeft = w.line.offsetLeft - w.el.clientWidth / 2;
      }});
    }});
    document.querySelectorAll(".copy").forEach(function (btn) {{
      btn.addEventListener("click", function () {{
        var code = btn.parentElement.querySelector(".lick");
        if (!code || !navigator.clipboard) return;
        navigator.clipboard.writeText(code.textContent).then(function () {{
          btn.textContent = "copied";
          setTimeout(function () {{ btn.textContent = "copy"; }}, 1400);
        }});
      }});
    }});
    document.addEventListener("keydown", function (e) {{
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.code === "Space") {{
        e.preventDefault();
        if (player.paused) player.play(); else player.pause();
      }} else if (e.code === "ArrowRight") {{
        e.preventDefault();
        player.currentTime = Math.min(
          player.duration || player.currentTime + 1,
          player.currentTime + 1
        );
      }} else if (e.code === "ArrowLeft") {{
        e.preventDefault();
        player.currentTime = Math.max(0, player.currentTime - 1);
      }}
    }});
  }})();
</script>
</body>
</html>
"""
