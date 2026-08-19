"""A self-contained HTML report — the play-along page, this tool's UI.

``analyze`` writes ``report.html`` next to ``brief.md``. Double-click it and
the browser shows the song: an audio player wired to a clickable section
timeline, one :class:`SectionPanel` per section that a single switcher flips
between piano roll, guitar tab, grand-staff sheet music, and chord chart —
every view with a playhead that follows playback, lyrics riding the charts,
alt-click note previews via Web Audio, ⌘-click A/B looping — plus the lyric
as sung, chord shape cards, stems, and the songwriting questions.

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
from . import chords as chords_mod
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
            '<rect class="nr" data-midi="{m}" data-start="{s}" '
            'data-dur="{d}" '
            'x="{x:.1f}" y="{y}" width="{w:.1f}" height="{h}" rx="2" '
            'opacity="{o:.2f}">'
            "<title>{name} · {t}s</title></rect>".format(
                m=n["midi"], s=round(float(n["start"]), 2),
                d=max(round(float(n["end"]) - float(n["start"]), 2), 0.05),
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


def _seq_x(t, times, xs=None, *, lead=2.0, colw=4.0):
    """Map a time onto sequence-spaced x — the single source of truth.

    The same interpolation the page script uses for the playhead: find
    the column sounding at *t* and glide toward the next in proportion.
    With *xs* the answer is in the SVG's pixels; without, in monospace
    ``ch`` columns (*lead* characters of margin, *colw* per column).
    Returns ``(value, unit)``.
    """
    import bisect

    idx = max(0, bisect.bisect_right(times, t) - 1)
    frac = 0.0
    if idx + 1 < len(times) and times[idx + 1] > times[idx]:
        frac = (t - times[idx]) / (times[idx + 1] - times[idx])
        frac = max(0.0, min(1.0, frac))
    if xs is not None:
        x = xs[idx]
        if idx + 1 < len(xs):
            x += frac * (xs[idx + 1] - xs[idx])
        return x, "px"
    return lead + colw / 2.0 + (idx + frac) * colw, "ch"


def _words_row(segments, start, end, *, times=None, xs=None, lead=2.0,
               colw=4.0):
    """The lyric, placed at its moment beneath a chart.

    Under the roll, each Whisper segment sits at its horizontal time
    fraction; under sequence-spaced charts (staff, tab) it sits at the
    same x as the column sounding then, via :func:`_seq_x`. The one being
    sung gets grown and accented by the page script, so eyes track words,
    notes, and names in one column.
    """
    span = max(float(end) - float(start), 0.001)
    inside = [
        s for s in segments or []
        if float(s["start"]) < end and float(s["end"]) > start
    ]
    if not inside:
        return ""
    spans = []
    for seg in inside:
        t = float(seg["start"])
        if times:
            x, unit = _seq_x(t, times, xs, lead=lead, colw=colw)
            left = "{:.1f}{}".format(x, unit)
        else:
            left = "{:.2f}%".format(
                max(0.0, min((t - start) / span * 100.0, 100.0))
            )
        spans.append(
            '<span class="word" style="left:{left}" data-start="{s}" '
            'data-end="{e}"><i>{text}</i></span>'.format(
                left=left, s=seg["start"], e=seg["end"],
                text=_esc(seg["text"]),
            )
        )
    return '<div class="words">{}</div>'.format("".join(spans))


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


def _dur_class(dur_beats):
    """Quantize an onset gap (in beats) to a note-value bucket."""
    if dur_beats >= 3.5:
        return "whole"
    if dur_beats >= 1.5:
        return "half"
    if dur_beats >= 0.75:
        return "quarter"
    if dur_beats >= 0.375:
        return "eighth"
    return "sixteenth"


def staff_svg(events, start, end, *, col_step=26, gutter=48, beats=None,
              downbeats=None):
    """A grand-staff pitch view with engraving-style spacing.

    Notes that sound together share one column, and columns advance by a
    fixed step the way engraved notation reads — not by wall-clock time.
    Returns ``(svg, times, xs, mids)``: each column's onset, its exact x
    in the SVG's pixel space (so the page script can put the playhead
    precisely on the notehead sounding now — the SVG renders 1:1 inside a
    horizontal scroller), and its MIDI notes (so an alt-click can sound
    the whole moment). Returns ``None`` with no notes in the window.

    Low notes sit on the bass staff instead of dangling from the treble on
    a tower of ledger lines; middle C takes the conventional single ledger
    between the staves.

    With allin1's *beats*/*downbeats* the staff also carries rhythm: a
    time signature, bar lines at the downbeats, and note values read off
    the onset gaps — open heads for halves, stems, beams across runs of
    eighths and sixteenths, flags on lone ones. It is honest quantization
    of a human performance, not engraving: the MusicXML export remains
    the route to strict notation.
    """
    cols = name_columns(
        [
            e for e in events or []
            if float(e["start"]) < end and float(e["end"]) > start
        ]
    )
    if not cols:
        return None

    # -- rhythm groundwork (only with a usable beat grid) -----------------
    import statistics

    rhythm = None
    beats = [float(b) for b in beats or []]
    downbeats = [float(d) for d in downbeats or []]
    if len(beats) >= 2:
        diffs = [b2 - b1 for b1, b2 in zip(beats, beats[1:]) if b2 > b1]
        beat_len = statistics.median(diffs) if diffs else 0
        if beat_len > 0:
            per_bar = None
            if len(downbeats) >= 2:
                counts = [
                    sum(1 for b in beats if d1 <= b < d2)
                    for d1, d2 in zip(downbeats, downbeats[1:])
                ]
                counts = [c for c in counts if c > 0]
                if counts:
                    per_bar = statistics.mode(counts)
            rhythm = {"beat_len": beat_len, "per_bar": per_bar}

    step = 4
    treble_lines = (30, 32, 34, 36, 38)  # E4 G4 B4 D5 F5
    bass_lines = (18, 20, 22, 24, 26)    # G2 B2 D3 F3 A3
    diatonics = [
        _diatonic(m)[0] for col in cols for m in col["midis"]
    ]
    d_hi = max(38, max(diatonics)) + 2
    d_lo = min(18, min(diatonics)) - 2

    def y(d):
        return 8 + (d_hi - d) * step

    ts_width = 18 if rhythm and rhythm["per_bar"] else 0
    xs = [gutter + 18 + ts_width + i * col_step for i in range(len(cols))]
    width = xs[-1] + 30
    height = y(d_lo) + 8

    times_list = [c["start"] for c in cols]
    classes, measures = [], []
    if rhythm:
        import bisect

        for i, t in enumerate(times_list):
            nxt = (
                times_list[i + 1] if i + 1 < len(times_list)
                else min(float(end), t + rhythm["beat_len"])
            )
            classes.append(_dur_class((nxt - t) / rhythm["beat_len"]))
            measures.append(bisect.bisect_right(downbeats, t))
    parts = [
        '<svg class="staff" viewBox="0 0 {w} {h}" width="{w}" '
        'height="{h}" xmlns="http://www.w3.org/2000/svg">'.format(
            w=width, h=height
        )
    ]
    for d in treble_lines + bass_lines:
        parts.append(
            '<line x1="8" y1="{y}" x2="{w}" y2="{y}" class="sline"/>'.format(
                y=y(d), w=width - 8
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
    for ci, (col, x) in enumerate(zip(cols, xs)):
        head_class = "sn"
        if rhythm and classes[ci] in ("whole", "half"):
            head_class = "sn open"
        for midi in col["midis"]:
            d, accidental = _diatonic(midi)
            ny = y(d)
            if d >= 29:
                if d < 30:  # middle C: one ledger below the treble staff
                    parts.append(
                        '<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" '
                        'class="ledger"/>'.format(x0=x - 8, x1=x + 8, y=y(28))
                    )
                for ledger in range(40, d + 1, 2):
                    parts.append(
                        '<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" '
                        'class="ledger"/>'.format(
                            x0=x - 8, x1=x + 8, y=y(ledger)
                        )
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
                        'class="ledger"/>'.format(
                            x0=x - 8, x1=x + 8, y=y(ledger)
                        )
                    )
            if accidental:
                parts.append(
                    '<text x="{x}" y="{y}" class="acc">{a}</text>'.format(
                        x=x - 13, y=ny + 3.5, a=accidental
                    )
                )
            parts.append(
                '<ellipse class="{cls}" data-midi="{m}" cx="{x:.1f}" '
                'cy="{y}" rx="4.6" ry="3.4">'
                "<title>{name} · {t}s</title></ellipse>".format(
                    cls=head_class, m=midi, x=x, y=ny,
                    name=_esc(note_name(midi, flats=True)),
                    t=round(float(col["start"]), 1),
                )
            )

    # -- rhythm layer: time signature, bar lines, stems, beams, flags -----
    if rhythm:
        if rhythm["per_bar"]:
            for num_d, den_d in ((34, 30), (22, 18)):  # treble, bass
                parts.append(
                    '<text x="{x}" y="{y1}" class="tsig">{n}</text>'
                    '<text x="{x}" y="{y2}" class="tsig">4</text>'.format(
                        x=gutter + 2, y1=y(num_d) - 1, y2=y(den_d) - 1,
                        n=rhythm["per_bar"],
                    )
                )
        for i in range(1, len(cols)):
            if measures[i] != measures[i - 1]:
                bx = (xs[i - 1] + xs[i]) / 2.0
                parts.append(
                    '<line x1="{x:.1f}" y1="{t}" x2="{x:.1f}" y2="{b}" '
                    'class="barline"/>'.format(x=bx, t=y(38), b=y(18))
                )
        for pred, middle in (
            (lambda d: d >= 29, 34),  # treble, middle line B4
            (lambda d: d < 29, 22),   # bass, middle line D3
        ):
            stems = {}
            for i, (col, x) in enumerate(zip(cols, xs)):
                ds = [
                    _diatonic(m)[0] for m in col["midis"]
                    if pred(_diatonic(m)[0])
                ]
                if not ds or classes[i] == "whole":
                    continue
                ys = [y(d) for d in ds]
                up = (sum(ds) / len(ds)) < middle
                if up:
                    stems[i] = [x + 4.4, max(ys) - 1, min(ys) - 24, True]
                else:
                    stems[i] = [x - 4.4, min(ys) + 1, max(ys) + 24, False]
            runs, cur = [], []
            for i in sorted(stems):
                if classes[i] not in ("eighth", "sixteenth"):
                    if cur:
                        runs.append(cur)
                        cur = []
                    # plain stem for quarters and halves
                    sx, y_from, tip, _up = stems[i]
                    parts.append(
                        '<line x1="{x:.1f}" y1="{a:.1f}" x2="{x:.1f}" '
                        'y2="{b:.1f}" class="stem"/>'.format(
                            x=sx, a=y_from, b=tip
                        )
                    )
                    continue
                joinable = (
                    cur
                    and i == cur[-1] + 1
                    and measures[i] == measures[cur[-1]]
                    and stems[i][3] == stems[cur[-1]][3]
                    and (times_list[i] - times_list[cur[-1]])
                    < 0.75 * rhythm["beat_len"]
                )
                if joinable:
                    cur.append(i)
                else:
                    if cur:
                        runs.append(cur)
                    cur = [i]
            if cur:
                runs.append(cur)
            for run in runs:
                up = stems[run[0]][3]
                if len(run) == 1:
                    i = run[0]
                    sx, y_from, tip, _up = stems[i]
                    parts.append(
                        '<line x1="{x:.1f}" y1="{a:.1f}" x2="{x:.1f}" '
                        'y2="{b:.1f}" class="stem"/>'.format(
                            x=sx, a=y_from, b=tip
                        )
                    )
                    flip = 1 if up else -1
                    flags = 2 if classes[i] == "sixteenth" else 1
                    for k in range(flags):
                        parts.append(
                            '<line x1="{x:.1f}" y1="{a:.1f}" x2="{x2:.1f}" '
                            'y2="{b:.1f}" class="flag"/>'.format(
                                x=sx, a=tip + flip * k * 5,
                                x2=sx + 6.5, b=tip + flip * (k * 5 + 8),
                            )
                        )
                    continue
                tips = [stems[i][2] for i in run]
                beam_y = min(tips) if up else max(tips)
                for i in run:
                    sx, y_from, _tip, _up = stems[i]
                    parts.append(
                        '<line x1="{x:.1f}" y1="{a:.1f}" x2="{x:.1f}" '
                        'y2="{b:.1f}" class="stem"/>'.format(
                            x=sx, a=y_from, b=beam_y
                        )
                    )
                x0, x1 = stems[run[0]][0], stems[run[-1]][0]
                parts.append(
                    '<line x1="{a:.1f}" y1="{y:.1f}" x2="{b:.1f}" '
                    'y2="{y:.1f}" class="beam"/>'.format(
                        a=x0, b=x1, y=beam_y
                    )
                )
                if all(classes[i] == "sixteenth" for i in run):
                    y2 = beam_y + (5 if up else -5)
                    parts.append(
                        '<line x1="{a:.1f}" y1="{y:.1f}" x2="{b:.1f}" '
                        'y2="{y:.1f}" class="beam"/>'.format(
                            a=x0, b=x1, y=y2
                        )
                    )

    parts.append("</svg>")
    return (
        "".join(parts), times_list, xs,
        [list(c["midis"]) for c in cols],
    )


class SectionPanel:
    """One section of the song, rendered as switchable play-along views.

    The panel is the report's unit of extensibility: each ``VIEWS`` row
    names a view key, its switcher label, and the method that renders it.
    Adding a view is one method plus one row — the global switcher, the
    panes, and the page script's toggling all derive from the registry.
    """

    VIEWS = (
        ("roll", "Piano roll", "roll_view"),
        ("gtab", "Guitar tab", "tab_view"),
        ("staff", "Sheet music", "staff_view"),
        ("chart", "Chord chart", "chart_view"),
    )

    EMPTY = '<p class="note">No notes transcribed here.</p>'

    def __init__(self, label, start, end, chord_events, *, all_notes,
                 lyr_segments, canon, structure, norm_file):
        self.label = label
        self.start = start
        self.end = end
        self.chord_events = chord_events  # [(symbol, t0, t1)…]
        self.symbols = [sym for sym, _t0, _t1 in chord_events]
        self.lyr_segments = lyr_segments
        self.canon = canon                # symbol -> (shorthand, positions)
        self.structure = structure
        self.norm_file = norm_file
        self.events = [
            e for e in all_notes
            if float(e["start"]) < end and float(e["end"]) > start
        ]

    # -- the four views ----------------------------------------------------

    def roll_view(self):
        """Piano roll with note names and lyrics aligned beneath it."""
        roll = note_roll(self.events, self.start, self.end)
        if not roll:
            return self.EMPTY
        return (
            '<div class="rollwrap" data-start="{t0}" '
            'data-end="{t1}">{roll}'
            '<div class="roll-line"></div></div>{names}{words}'.format(
                t0=self.start, t1=self.end, roll=roll,
                names=_names_row(self.events, self.start, self.end),
                words=_words_row(self.lyr_segments, self.start, self.end),
            )
        )

    def tab_view(self):
        """Every note as guitar tab, in selectable neck positions.

        The audio cannot say which string was played, so the same notes
        are offered fingered from several positions. data-times lets the
        script walk a playhead through the text, one monospace column
        each; data-cells (string:midi per column) lets alt-clicks sound
        the note.
        """
        if not self.events:
            return self.EMPTY
        ordered = sorted(
            self.events, key=lambda e: (float(e["start"]), e["midi"])
        )
        tab_times = [round(float(e["start"]), 2) for e in ordered]
        times = ",".join(str(t) for t in tab_times)
        tab_words = _words_row(
            self.lyr_segments, self.start, self.end, times=tab_times
        )
        variants, seen_tabs = [], set()
        for pos_label, seed in (("low", None), ("5th", 5), ("9th", 9)):
            positioned = notes_mod.choose_positions(
                ordered, strings=(1, 2, 3, 4, 5, 6), prefer_fret=seed
            )
            tab_text = notes_mod.render_tab(
                positioned, strings=(1, 2, 3, 4, 5, 6), width=3
            )
            if tab_text in seen_tabs:
                continue
            seen_tabs.add(tab_text)
            cells = ";".join(
                "{}:{}".format(p["string"], p["midi"])
                if p.get("string") else ""
                for p in positioned
            )
            variants.append((pos_label, tab_text, cells))
        buttons = "".join(
            '<button type="button" class="postab{act}" '
            'data-pos="{i}">{lbl}</button>'.format(
                act=" active" if i == 0 else "", i=i, lbl=_esc(lbl)
            )
            for i, (lbl, _t, _c) in enumerate(variants)
        )
        bodies = "".join(
            '<div class="tabvar{act}" data-pos="{i}">'
            '<div class="tabwrap" data-start="{t0}" '
            'data-end="{t1}" data-times="{times}" data-lead="2" '
            'data-colw="4" data-cells="{cells}">'
            '<div class="tabinner">'
            '<pre class="tab">{tab}</pre>{words}'
            '<div class="roll-line tab-line"></div></div></div>'
            "</div>".format(
                act=" active" if i == 0 else "", i=i,
                t0=self.start, t1=self.end, times=times,
                tab=_esc(tab_text), cells=cells, words=tab_words,
            )
            for i, (_lbl, tab_text, cells) in enumerate(variants)
        )
        selector = ""
        if len(variants) > 1:
            selector = (
                '<div class="posbar" title="The recording cannot '
                "say which string was played — same notes, "
                'different neck positions">'
                '<span class="poslabel">position</span>{}</div>'
            ).format(buttons)
        return selector + bodies

    def staff_view(self):
        """Grand staff, engraving-spaced and scrollable.

        data-xs carries each column's exact x so the playhead sits on the
        notehead sounding now; data-mids lets alt-clicks sound the whole
        moment. The beat grid, when allin1 produced one, adds the time
        signature, bar lines, and beamed rhythms.
        """
        built = staff_svg(
            self.events, self.start, self.end,
            beats=[
                b for b in (self.structure.get("beat_times") or [])
                if self.start - 1 <= b < self.end + 1
            ],
            downbeats=[
                d for d in (self.structure.get("downbeat_times") or [])
                if self.start <= d < self.end
            ],
        )
        if not built:
            return self.EMPTY
        st_svg, st_times, st_xs, st_mids = built
        return (
            '<div class="tabwrap staffwrap" data-start="{t0}" '
            'data-end="{t1}" data-times="{times}" data-xs="{xs}" '
            'data-mids="{mids}">'
            '<div class="tabinner">{staff}{words}'
            '<div class="roll-line tab-line"></div></div>'
            "</div>".format(
                t0=self.start, t1=self.end,
                times=",".join(str(round(t, 2)) for t in st_times),
                xs=",".join(str(round(x, 1)) for x in st_xs),
                mids=";".join(
                    ",".join(str(m) for m in col) for col in st_mids
                ),
                staff=st_svg,
                words=_words_row(
                    self.lyr_segments, self.start, self.end,
                    times=st_times, xs=st_xs,
                ),
            )
        )

    def chart_view(self):
        """Chord chips plus the textbook-grip tab chart.

        The playhead walks chord to chord; data-cells carries each grip's
        string:midi pairs so an alt-click strums the whole chord.
        """
        chips = "".join(
            '<span class="chip" data-start="{t0}" data-end="{t1}">'
            "{sym}</span>".format(t0=t0, t1=t1, sym=_esc(sym))
            for sym, t0, t1 in self.chord_events
        )
        chord_tab = chords_mod.render_chord_tab(
            [
                {"voicing": {"positions": self.canon[sym][1]}}
                if self.canon.get(sym) and self.canon[sym][1]
                else {"voicing": None}
                for sym in self.symbols
            ]
        )
        chord_times = ",".join(
            str(round(t0, 2)) for _sym, t0, _t1 in self.chord_events
        )
        chord_cells = ";".join(
            ",".join(
                "{}:{}".format(
                    p["string"],
                    notes_mod.STANDARD_TUNING[p["string"]] + p["fret"],
                )
                for p in (self.canon.get(sym) and self.canon[sym][1] or [])
            )
            for sym, _t0, _t1 in self.chord_events
        )
        return (
            '<div class="chips">{chips}</div>'
            '<div class="tabwrap" data-start="{t0}" data-end="{t1}" '
            'data-times="{times}" data-lead="2" data-colw="7" '
            'data-cells="{cells}">'
            '<div class="tabinner"><pre class="tab">{tab}</pre>'
            '<div class="roll-line tab-line"></div></div></div>'.format(
                chips=chips, t0=self.start, t1=self.end, times=chord_times,
                cells=chord_cells, tab=_esc(chord_tab),
            )
        )

    # -- assembly ------------------------------------------------------------

    def render(self):
        """The whole panel: summary line, view panes, lick command."""
        panes = "".join(
            '<div class="view{act}" data-view="{key}">{body}</div>'.format(
                act=" active" if i == 0 else "", key=key,
                body=getattr(self, method)(),
            )
            for i, (key, _label, method) in enumerate(self.VIEWS)
        )
        lick = ""
        if self.norm_file:
            lick = (
                '<div class="lickrow"><code class="lick">music-stack '
                "lick --input {} --start {} --end {}</code>"
                '<button class="copy" type="button">copy</button>'
                "</div>".format(
                    _esc(self.norm_file), _clock(self.start),
                    _clock(self.end),
                )
            )
        hue = _SECTION_HUES.get(str(self.label or "").lower(), 210)
        return (
            '<section class="panel scoreblock" data-start="{t0}" '
            'data-end="{t1}">'
            '<header class="blockhead"><span class="seclabel" '
            'style="--hue:{hue}">{label}</span>'
            '<span class="range">{c0}–{c1}</span>'
            '<span class="prog-mini">{mini}</span>'
            '<button class="tonesbtn" type="button" '
            'title="Play this section\'s transcribed notes as tones, at '
            'tempo">▶ tones</button></header>'
            '<div class="views">{panes}</div>'
            "{lick}</section>".format(
                t0=self.start, t1=self.end, hue=hue,
                label=_esc(self.label or "all"),
                c0=_clock(self.start), c1=_clock(self.end),
                mini=_esc(" · ".join(self.symbols[:8])
                          + (" …" if len(self.symbols) > 8 else "")),
                panes=panes, lick=lick,
            )
        )

    @classmethod
    def switcher(cls):
        """The one global view toggle, generated from the same registry."""
        return '<div class="vtabs">{}</div>'.format(
            "".join(
                '<button type="button" class="vtab{act}" '
                'data-view="{key}">{label}</button>'.format(
                    act=" active" if i == 0 else "", key=key, label=label
                )
                for i, (key, label, _method) in enumerate(cls.VIEWS)
            )
        )


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
        segments = lyrics.get("segments") or []
        if segments:
            lines = "".join(
                '<p class="lline" data-start="{s}" data-end="{e}">'
                '<span class="lt">{clock}</span>'
                '<span class="ltext">{text}</span></p>'.format(
                    s=seg["start"], e=seg["end"],
                    clock=_clock(seg["start"]), text=_esc(seg["text"]),
                )
                for seg in segments
            )
            body = '<div class="card-block lyriclines">{}</div>'.format(lines)
        else:
            body = '<div class="card-block"><pre class="lyrics">{}</pre>' \
                   "</div>".format(_esc(lyrics["text"]))
        lyrics_html = (
            "<h2>Lyrics as sung</h2>"
            '<p class="note">{}</p>{}'.format(_esc(provenance), body)
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
        canon = {
            sym: (short, positions)
            for sym, short, positions in brief_mod.canonical_shapes(chords)
        }
        panels = []
        shown = set()
        for label, s_start, s_end, events in brief_mod.progression_events(
            chords, sections
        ):
            panel = SectionPanel(
                label, s_start, s_end, events,
                all_notes=(stages.get("chords") or {}).get("notes") or [],
                lyr_segments=(stages.get("lyrics") or {}).get("segments")
                or [],
                canon=canon,
                structure=structure,
                norm_file=(stages.get("normalize") or {}).get("file"),
            )
            shown.update(panel.symbols)
            panels.append(panel.render())
        prog_html = ""
        if panels:
            # One continuous score surface: the sections flow into each
            # other, separated only by their header lines.
            prog_html = '<div class="progression score">{}</div>'.format(
                "".join(panels)
            )
            # One switcher drives every section; it lives in the sticky
            # player bar so it is always in reach.
            viewbar_html = SectionPanel.switcher()
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
  /* A deliberately light, editorial surface: warm paper, soft ink,
     terracotta for the interactive layer, slate-blue for the notes
     themselves, hairline borders instead of heavy shadows. */
  :root {{
    --bg: #f7f5f0; --card: #fffdf8; --fg: #2a2722; --muted: #877f6f;
    --line: #e6e0d2; --accent: #bc5a3c; --accent-soft: #f7e9e2;
    --panel: #f1ede2; --note: #54677d;
  }}
  * {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{
    font: 15px/1.6 -apple-system, BlinkMacSystemFont, "SF Pro Text",
      Inter, "Segoe UI", Roboto, sans-serif;
    margin: 0; background: var(--bg); color: var(--fg);
    -webkit-font-smoothing: antialiased;
  }}
  main {{ max-width: 62rem; margin: 0 auto; padding: 1.4rem 1.2rem 4rem; }}
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
    background: hsl(var(--hue,210) 30% 50%);
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
  .missing .chip {{ background: #f9ece7; color: #a2401f;
    border: 1px solid #ecccbd; }}

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

  /* One continuous score: sections flow inside a single card, joined by
     hairline rules; the playing section gets a quiet accent bar in the
     margin instead of its own box. */
  .score {{
    background: var(--card); border: 1px solid var(--line);
    border-radius: 16px; padding: .4rem 1.6rem .6rem; margin: .9rem 0;
  }}
  .scoreblock {{
    position: relative; padding: 1.05rem 0 1.25rem;
    border-top: 1px solid
      color-mix(in srgb, var(--line) 55%, transparent);
  }}
  .scoreblock:first-child {{ border-top: 0; }}
  .scoreblock.now::before {{
    content: ""; position: absolute; left: -1.6rem; top: 1rem;
    bottom: 1rem; width: 3px; border-radius: 0 2px 2px 0;
    background: var(--accent);
  }}
  .blockhead {{
    display: flex; align-items: baseline; gap: .6rem; flex-wrap: wrap;
    margin-bottom: .35rem;
  }}
  .seclabel {{
    font-size: .72rem; font-weight: 700; letter-spacing: .04em;
    text-transform: uppercase; color: #fff; padding: .12rem .6rem;
    border-radius: 999px; background: hsl(var(--hue,210) 28% 48%);
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
    background: linear-gradient(180deg, #fffdf9, #faf7f0); }}
  .roll {{ display: block; }}
  .roll .octave {{ stroke: var(--line); stroke-width: 1; }}
  .roll .octlabel {{ fill: var(--muted); font: 600 9px sans-serif; }}
  .roll .nr {{ fill: var(--note); cursor: pointer; }}
  .roll .nr:hover {{ fill: var(--accent); }}
  .roll-line {{
    position: absolute; top: 0; bottom: 0; left: 0; width: 1.5px;
    background: var(--accent); display: none; pointer-events: none;
  }}
  .loop-shade {{
    position: absolute; top: 0; bottom: 0; pointer-events: none;
    background: color-mix(in srgb, var(--accent) 13%, transparent);
    border-left: 2px solid var(--accent);
    border-right: 2px solid var(--accent); z-index: 1;
  }}
  .loopbadge {{ margin-left: .6rem; color: var(--accent);
    font-weight: 650; }}
  .tonesbtn {{ display: none; margin-left: auto; border: 1px solid
    var(--accent); background: var(--accent-soft); color: var(--accent);
    border-radius: 999px; padding: .1rem .6rem; font: 600 .74rem
    -apple-system, sans-serif; cursor: pointer; }}
  body.altdown .tonesbtn, .tonesbtn.playing {{ display: inline-block; }}
  .tonesbtn.playing {{ background: var(--accent); color: #fff; }}

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
  .posbar {{ display: flex; align-items: center; gap: .35rem;
    margin-bottom: .45rem; }}
  .poslabel {{ color: var(--muted); font-size: .72rem;
    text-transform: uppercase; letter-spacing: .07em; }}
  .postab {{ border: 1px solid var(--line); background: var(--card);
    border-radius: 999px; padding: .1rem .6rem; font: inherit;
    font-size: .74rem; color: var(--muted); cursor: pointer; }}
  .postab:hover {{ border-color: var(--accent); color: var(--accent); }}
  .postab.active {{ background: var(--accent); border-color: var(--accent);
    color: #fff; }}
  .tabvar {{ display: none; }}
  .tabvar.active {{ display: block; }}

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

  .karaoke {{ margin-top: .55rem; text-align: center; font-size: .95rem;
    font-weight: 600; min-height: 1.35rem; }}
  .speedbar {{ display: flex; align-items: center; gap: .3rem;
    margin-top: .55rem; flex-wrap: wrap; }}
  .speedbar .note {{ margin-left: .3rem; }}
  .words {{ position: relative; height: 1.35rem; margin-top: .1rem; }}
  .word {{ position: absolute; top: 0; font-size: .66rem;
    color: var(--muted); white-space: nowrap; max-width: 42%;
    overflow: hidden; text-overflow: ellipsis; cursor: pointer;
    transition: font-size .12s; }}
  .word:hover {{ color: var(--accent); z-index: 4; }}
  .word.now {{ color: var(--accent); font-weight: 700;
    font-size: .78rem; z-index: 3; background: var(--card);
    max-width: 70%; }}
  .word i {{ font-style: normal; }}
  /* Inside sequence-spaced charts the span's own font must match the
     chart's ch grid for left: Nch to land right; the visible text keeps
     the small lyric size via the inner element. */
  /* Match the pre's left padding so ch coordinates line up; the staff
     svg starts flush left, so there the offset is zero. */
  .tabinner .words {{ cursor: default; margin: .1rem 0 .3rem .9rem; }}
  .staffwrap .words {{ margin-left: 0; }}
  .tabinner .word {{
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: .78rem; max-width: none; }}
  .tabinner .word i {{
    font: 500 .64rem/1.4 -apple-system, BlinkMacSystemFont, "SF Pro Text",
      Inter, "Segoe UI", Roboto, sans-serif; }}
  .tabinner .word.now i {{ font-weight: 700; }}
  .lyriclines .lline {{ margin: .3rem 0; cursor: pointer; }}
  .lline .lt {{ color: var(--muted); font-size: .7rem; margin-right: .6rem;
    font-variant-numeric: tabular-nums; }}
  .lline:hover .ltext {{ color: var(--accent); }}
  .lline.now .ltext {{ color: var(--accent); font-weight: 650; }}

  .tabwrap {{ overflow-x: auto; border: 1px solid var(--line);
    border-radius: 9px; background: var(--panel); }}
  .tabinner {{ position: relative; display: inline-block;
    min-width: 100%; }}
  .tabwrap .tab {{ margin: 0; border: 0; background: transparent;
    overflow: visible; }}
  .tab-line {{ display: none; margin-left: .9rem; }}

  .tabwrap.staffwrap {{ background: var(--card); cursor: pointer; }}
  .tabinner svg {{ display: block; }}
  .staff {{ display: block; }}
  .staff .sline {{ stroke: #b5ad9b; stroke-width: 1; }}
  .staff .ledger {{ stroke: #b5ad9b; stroke-width: 1; }}
  .staff .clef {{ font-size: 40px; fill: var(--fg); }}
  .staff .bclef {{ font-size: 30px; }}
  .staff .acc {{ font-size: 10px; fill: var(--fg); }}
  .staff .sn {{ fill: var(--note); cursor: pointer; }}
  .staff .sn:hover {{ fill: var(--accent); }}
  .staff .sn.open {{ fill: var(--card); stroke: var(--note);
    stroke-width: 1.6; }}
  .staff .stem {{ stroke: var(--note); stroke-width: 1.4; }}
  .staff .beam {{ stroke: var(--note); stroke-width: 3.2; }}
  .staff .flag {{ stroke: var(--note); stroke-width: 1.5; }}
  .staff .barline {{ stroke: #b5ad9b; stroke-width: 1; }}
  .staff .tsig {{ fill: var(--fg); font: 700 15px Georgia, serif; }}

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
  .chordbox .fret, .chordbox .string {{ stroke: #d8d0bf; stroke-width: 1; }}
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
<kbd>→</kbd> scrub · the speed pills (or <kbd>[</kbd> <kbd>]</kbd>) slow
the song down without changing pitch — the browser time-stretches, and
every chart, lyric, and loop stays in sync · click the timeline, a chord chip, a note name, or
anywhere in a roll or staff to jump there · the toggle switches every
section between Piano roll, Guitar tab, Sheet music, and Chord chart ·
a plain click moves the playhead without starting playback ·
<kbd>⌥</kbd>-click a notehead to hear that pitch ring, ⌥-click beside
the notes to hear everything sounding at that moment (chord columns
strum the grip), and ⌥-drag across a chart to play through the notes
as you sweep — they hold while you hold · holding <kbd>⌥</kbd> also
surfaces a ▶ tones button on each section that plays its transcription
back as synth at the song's own tempo ·
each section's <code>music-stack lick</code> command re-transcribes just
that span for note-perfect tab, scale, and sheet music.</p>
<p><b>Accuracy</b> — transcription is machine listening on a full mix:
trust the progression and timing, and verify oddball chords or fast licks
with <code>lick</code> on a tight time window. Tab fingerings are
suggestions — the recording cannot say which string was played, so the
position selector offers the same notes in different places on the
neck.</p>
</div>
<div class="playerbar">
{audio}
{timeline}
<div class="karaoke" id="karaoke" hidden></div>
{viewbar}
<div class="speedbar"><span class="poslabel">speed</span>
<button type="button" class="postab" data-rate="0.5">0.5×</button>
<button type="button" class="postab" data-rate="0.65">0.65×</button>
<button type="button" class="postab" data-rate="0.75">0.75×</button>
<button type="button" class="postab" data-rate="0.85">0.85×</button>
<button type="button" class="postab active" data-rate="1">1×</button>
<span class="note">same pitch, slower song</span></div>
<div class="keys"><kbd>space</kbd> play / pause &nbsp; <kbd>←</kbd>
<kbd>→</kbd> scrub 1s &nbsp; <kbd>[</kbd> <kbd>]</kbd> slower / faster
(pitch stays put) &nbsp; click moves the playhead &nbsp;
<kbd>⌥</kbd>-click a note (or a moment) to hear it, ⌥-drag to play
through, hold <kbd>⌥</kbd> for each section's ▶ tones button &nbsp;
<kbd>⌘</kbd>-click two spots to loop a passage, <kbd>esc</kbd> clears
<span class="loopbadge" id="loopbadge" hidden></span></div>
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
    document.querySelectorAll(".view[data-view=gtab]").forEach(
      function (view) {{
        var btns = view.querySelectorAll(".postab");
        btns.forEach(function (btn) {{
          btn.addEventListener("click", function () {{
            btns.forEach(function (b) {{
              b.classList.toggle("active", b === btn);
            }});
            view.querySelectorAll(".tabvar").forEach(function (tv) {{
              tv.classList.toggle(
                "active", tv.dataset.pos === btn.dataset.pos
              );
            }});
          }});
        }});
      }}
    );
    if (!player) return;

    // -- note preview: click a notehead, hear its pitch ------------------
    var audioCtx = null;
    function previewTone(midis) {{
      try {{
        audioCtx = audioCtx ||
          new (window.AudioContext || window.webkitAudioContext)();
      }} catch (err) {{ return; }}
      var now = audioCtx.currentTime;
      midis.forEach(function (m, i) {{
        var at = now + i * 0.035;  // chords strum slightly, like a hand
        var osc = audioCtx.createOscillator();
        var filter = audioCtx.createBiquadFilter();
        var gain = audioCtx.createGain();
        osc.type = "triangle";
        osc.frequency.value = 440 * Math.pow(2, (m - 69) / 12);
        filter.type = "lowpass";
        filter.frequency.value = 2400;
        gain.gain.setValueAtTime(0.0001, at);
        gain.gain.exponentialRampToValueAtTime(
          0.28 / Math.sqrt(midis.length), at + 0.012
        );
        gain.gain.exponentialRampToValueAtTime(0.0001, at + 1.5);
        osc.connect(filter);
        filter.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start(at);
        osc.stop(at + 1.6);
      }});
    }}
    // Sustained voices for alt-drag auditioning: start on entry, hold
    // while the pointer stays, cross-fade on the next moment, release
    // with a fade on mouseup.
    var voices = [];
    function releaseVoices(fade) {{
      if (!audioCtx) {{ voices = []; return; }}
      var now = audioCtx.currentTime;
      voices.forEach(function (v) {{
        try {{
          v.gain.gain.cancelScheduledValues(now);
          v.gain.gain.setValueAtTime(
            Math.max(v.gain.gain.value, 0.0001), now
          );
          v.gain.gain.exponentialRampToValueAtTime(0.0001, now + fade);
          v.osc.stop(now + fade + 0.05);
        }} catch (err) {{}}
      }});
      voices = [];
    }}
    function holdTones(midis) {{
      try {{
        audioCtx = audioCtx ||
          new (window.AudioContext || window.webkitAudioContext)();
      }} catch (err) {{ return; }}
      releaseVoices(0.22);
      var now = audioCtx.currentTime;
      midis.forEach(function (m) {{
        var osc = audioCtx.createOscillator();
        var filter = audioCtx.createBiquadFilter();
        var gain = audioCtx.createGain();
        osc.type = "triangle";
        osc.frequency.value = 440 * Math.pow(2, (m - 69) / 12);
        filter.type = "lowpass";
        filter.frequency.value = 2400;
        gain.gain.setValueAtTime(0.0001, now);
        gain.gain.exponentialRampToValueAtTime(
          0.26 / Math.sqrt(midis.length), now + 0.02
        );
        osc.connect(filter);
        filter.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start(now);
        voices.push({{osc: osc, gain: gain}});
      }});
    }}

    // -- speed: time-stretch without pitch shift -------------------------
    // The browser's own stretcher (playbackRate + preservesPitch) slows
    // the song while every playhead and highlight follows currentTime.
    var RATES = [0.5, 0.65, 0.75, 0.85, 1];
    var speedBtns = document.querySelectorAll(".speedbar [data-rate]");
    function setSpeed(rate) {{
      player.playbackRate = rate;
      player.preservesPitch = true;
      player.webkitPreservesPitch = true;
      speedBtns.forEach(function (b) {{
        b.classList.toggle(
          "active", parseFloat(b.dataset.rate) === rate
        );
      }});
    }}
    speedBtns.forEach(function (btn) {{
      btn.addEventListener("click", function () {{
        setSpeed(parseFloat(btn.dataset.rate));
      }});
    }});
    function nudgeSpeed(step) {{
      var current = player.playbackRate || 1;
      var idx = 0;
      for (var i = 0; i < RATES.length; i++) {{
        if (Math.abs(RATES[i] - current) <
            Math.abs(RATES[idx] - current)) idx = i;
      }}
      idx = Math.max(0, Math.min(RATES.length - 1, idx + step));
      setSpeed(RATES[idx]);
    }}
    setSpeed(1);

    // -- tones playback: the transcription rendered as synth, at tempo --
    var tones = {{nodes: [], btn: null, timer: null}};
    var compressor = null;
    function toneBus() {{
      audioCtx = audioCtx ||
        new (window.AudioContext || window.webkitAudioContext)();
      if (!compressor) {{
        compressor = audioCtx.createDynamicsCompressor();
        compressor.connect(audioCtx.destination);
      }}
      return compressor;
    }}
    function stopTones() {{
      if (tones.timer) clearTimeout(tones.timer);
      var now = audioCtx ? audioCtx.currentTime : 0;
      tones.nodes.forEach(function (v) {{
        try {{
          v.gain.gain.cancelScheduledValues(now);
          v.gain.gain.setValueAtTime(
            Math.max(v.gain.gain.value, 0.0001), now
          );
          v.gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.15);
          v.osc.stop(now + 0.2);
        }} catch (err) {{}}
      }});
      tones.nodes = [];
      if (tones.btn) {{
        tones.btn.textContent = "▶ tones";
        tones.btn.classList.remove("playing");
      }}
      tones.btn = null;
      tones.timer = null;
    }}
    function playTones(panel, btn) {{
      var notes = [];
      panel.querySelectorAll(".nr[data-midi][data-start]").forEach(
        function (n) {{
          notes.push({{
            midi: parseInt(n.dataset.midi, 10),
            start: parseFloat(n.dataset.start),
            dur: parseFloat(n.dataset.dur || "0.3")
          }});
        }}
      );
      if (!notes.length) return;
      var bus;
      try {{ bus = toneBus(); }} catch (err) {{ return; }}
      stopTones();
      var first = Infinity;
      notes.forEach(function (n) {{ first = Math.min(first, n.start); }});
      // The synth rendition follows the practice speed too.
      var rate = player.playbackRate || 1;
      var base = audioCtx.currentTime + 0.08;
      var last = 0;
      notes.forEach(function (n) {{
        var at = base + (n.start - first) / rate;
        var dur = Math.max(n.dur, 0.08) / rate;
        var osc = audioCtx.createOscillator();
        var filter = audioCtx.createBiquadFilter();
        var gain = audioCtx.createGain();
        osc.type = "triangle";
        osc.frequency.value = 440 * Math.pow(2, (n.midi - 69) / 12);
        filter.type = "lowpass";
        filter.frequency.value = 2400;
        gain.gain.setValueAtTime(0.0001, at);
        gain.gain.exponentialRampToValueAtTime(0.18, at + 0.012);
        gain.gain.setValueAtTime(0.18, at + Math.max(dur - 0.1, 0.02));
        gain.gain.exponentialRampToValueAtTime(0.0001, at + dur + 0.15);
        osc.connect(filter);
        filter.connect(gain);
        gain.connect(bus);
        osc.start(at);
        osc.stop(at + dur + 0.25);
        tones.nodes.push({{osc: osc, gain: gain}});
        last = Math.max(last, (n.start - first) / rate + dur);
      }});
      tones.btn = btn;
      btn.textContent = "■ stop";
      btn.classList.add("playing");
      tones.timer = setTimeout(stopTones, (last + 0.5) * 1000);
    }}
    document.querySelectorAll(".tonesbtn").forEach(function (btn) {{
      btn.addEventListener("click", function (e) {{
        e.preventDefault();
        e.stopPropagation();
        if (tones.btn === btn) {{
          stopTones();
        }} else {{
          playTones(btn.closest(".panel"), btn);
        }}
      }});
    }});
    // The buttons surface while alt is held (and stay while playing).
    document.addEventListener("keydown", function (e) {{
      if (e.key === "Alt") document.body.classList.add("altdown");
    }});
    document.addEventListener("keyup", function (e) {{
      if (e.key === "Alt") document.body.classList.remove("altdown");
    }});
    window.addEventListener("blur", function () {{
      document.body.classList.remove("altdown");
    }});

    // Capture-phase: swallow the click that follows an audition drag;
    // otherwise, with alt held, a click on a notehead sounds exactly
    // that note. Alt-clicks that miss a note fall through to the chart
    // handlers, which sound the whole moment instead.
    var suppressClick = false;
    document.addEventListener("click", function (e) {{
      if (suppressClick) {{
        suppressClick = false;
        e.stopPropagation();
        e.preventDefault();
        return;
      }}
      if (!e.altKey || e.metaKey || e.ctrlKey) return;
      var target = e.target;
      var el = target && target.closest
        ? target.closest(".nr[data-midi], .sn[data-midi]") : null;
      if (!el) return;
      e.stopPropagation();
      e.preventDefault();
      previewTone([parseInt(el.dataset.midi, 10)]);
    }}, true);

    // -- A/B loop: cmd-click two spots, escape clears -------------------
    var loop = {{a: null, b: null}};
    function clockfmt(t) {{
      t = Math.max(0, Math.floor(t));
      return Math.floor(t / 60) + ":" + ("0" + (t % 60)).slice(-2);
    }}
    function seqPos(w, t) {{
      var idx = 0;
      for (var i = 0; i < w.times.length; i++) {{
        if (w.times[i] <= t) idx = i; else break;
      }}
      var frac = 0;
      if (idx + 1 < w.times.length && w.times[idx + 1] > w.times[idx]) {{
        frac = (t - w.times[idx]) / (w.times[idx + 1] - w.times[idx]);
        frac = Math.max(0, Math.min(1, frac));
      }}
      if (w.xs && w.xs.length === w.times.length) {{
        var x = w.xs[idx];
        if (idx + 1 < w.xs.length) x += frac * (w.xs[idx + 1] - w.xs[idx]);
        return {{v: x, unit: "px"}};
      }}
      var col = idx + (idx + 1 < w.times.length ? frac : 0);
      return {{v: w.lead + col * w.colw + w.colw / 2, unit: "ch"}};
    }}
    function addShade(parent, left, width, unit) {{
      var el = document.createElement("div");
      el.className = "loop-shade";
      el.style.left = left + unit;
      el.style.width = Math.max(width, 0) + unit;
      parent.appendChild(el);
    }}
    function renderLoop() {{
      document.querySelectorAll(".loop-shade").forEach(function (el) {{
        el.remove();
      }});
      var badge = document.getElementById("loopbadge");
      if (badge) {{
        badge.hidden = loop.a === null;
        if (loop.b !== null) {{
          badge.textContent = "looping " + clockfmt(loop.a) + "–" +
            clockfmt(loop.b);
        }} else if (loop.a !== null) {{
          badge.textContent = "loop start " + clockfmt(loop.a) +
            " — ⌘-click the end";
        }}
      }}
      if (loop.a === null) return;
      var b = loop.b === null ? loop.a : loop.b;
      if (timeline && player.duration) {{
        addShade(timeline, 100 * loop.a / player.duration,
                 100 * (b - loop.a) / player.duration, "%");
      }}
      rolls.forEach(function (wrap) {{
        var t0 = parseFloat(wrap.dataset.start);
        var t1 = parseFloat(wrap.dataset.end);
        if (b < t0 || loop.a >= t1) return;
        var a1 = Math.max(loop.a, t0), b1 = Math.min(b, t1);
        addShade(wrap, 100 * (a1 - t0) / (t1 - t0),
                 100 * (b1 - a1) / (t1 - t0), "%");
      }});
      tabwraps.forEach(function (w) {{
        if (b < w.t0 || loop.a >= w.t1 || !w.times.length) return;
        var inner = w.el.querySelector(".tabinner");
        if (!inner) return;
        var p0 = seqPos(w, Math.max(loop.a, w.t0));
        var p1 = seqPos(w, Math.min(b, w.t1));
        addShade(inner, p0.v, p1.v - p0.v, p0.unit);
      }});
    }}
    function setLoopPoint(t) {{
      if (loop.a === null || loop.b !== null) {{
        loop.a = t;
        loop.b = null;
      }} else {{
        loop.b = t;
        if (loop.b < loop.a) {{
          var swap = loop.a;
          loop.a = loop.b;
          loop.b = swap;
        }}
      }}
      renderLoop();
    }}
    function clearLoop() {{
      loop.a = loop.b = null;
      renderLoop();
    }}
    function seekOrLoop(e, t) {{
      if (e.metaKey || e.ctrlKey) {{
        e.preventDefault();
        setLoopPoint(t);
        return;
      }}
      // A plain click only moves the playhead; play stays where it was
      // (space starts it, and an already-playing song keeps playing).
      player.currentTime = t;
    }}

    document.querySelectorAll(
      ".seg[data-start], .chip[data-start], .ncol[data-start], " +
      ".word[data-start], .lline[data-start]"
    ).forEach(function (el) {{
      el.addEventListener("click", function (e) {{
        seekOrLoop(e, parseFloat(el.dataset.start));
      }});
    }});
    var timed = document.querySelectorAll(
      ".panel[data-start], .chip[data-start], .word[data-start], " +
      ".lline[data-start]"
    );
    var karaoke = document.getElementById("karaoke");
    var llines = document.querySelectorAll(".lline[data-start]");
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
      var entry = {{
        el: w,
        times: (w.dataset.times || "").split(",").map(parseFloat)
          .filter(isFinite),
        xs: w.dataset.xs
          ? w.dataset.xs.split(",").map(parseFloat).filter(isFinite)
          : null,
        // Per-column MIDI notes, from either encoding: "s:m" fret cells
        // (tab, chord chart) or bare midi lists (staff).
        mids: w.dataset.cells
          ? w.dataset.cells.split(";").map(function (col) {{
              return col.split(",").map(function (pair) {{
                return parseInt(pair.split(":").pop(), 10);
              }}).filter(isFinite);
            }})
          : (w.dataset.mids
            ? w.dataset.mids.split(";").map(function (col) {{
                return col.split(",").map(Number).filter(isFinite);
              }})
            : null),
        line: w.querySelector(".tab-line"),
        t0: parseFloat(w.dataset.start),
        t1: parseFloat(w.dataset.end),
        lead: parseFloat(w.dataset.lead || 2),
        colw: parseFloat(w.dataset.colw || 4)
      }};
      entry.el = w;
      tabwraps.push(entry);
      w.addEventListener("click", function (e) {{
        var best = wrapColumn(entry, e.clientX);
        if (best === null) return;
        if (e.altKey && !(e.metaKey || e.ctrlKey)) {{
          // Alt-click: sound the whole column at that moment.
          var midis = entry.mids && entry.mids[best];
          if (midis && midis.length) previewTone(midis);
          return;
        }}
        seekOrLoop(e, entry.times[best]);
      }});
    }});
    // The column under a pointer position in a sequence-spaced chart:
    // staff by nearest column x, tab by converting into monospace
    // columns. Shared by clicks and alt-drags.
    function wrapColumn(entry, clientX) {{
      if (!entry.times.length) return null;
      var inner = entry.el.querySelector(".tabinner");
      if (!inner) return null;
      var best = 0;
      if (entry.xs) {{
        var x = clientX - inner.getBoundingClientRect().left;
        for (var i = 1; i < entry.xs.length; i++) {{
          if (Math.abs(entry.xs[i] - x) < Math.abs(entry.xs[best] - x)) {{
            best = i;
          }}
        }}
      }} else {{
        var pre = inner.querySelector(".tab");
        if (!pre) return null;
        if (!entry.chpx) {{
          var probe = document.createElement("span");
          probe.style.cssText =
            "position:absolute;visibility:hidden;width:1ch";
          pre.appendChild(probe);
          entry.chpx = probe.offsetWidth || 8;
          entry.padLeft =
            parseFloat(getComputedStyle(pre).paddingLeft) || 0;
          pre.removeChild(probe);
        }}
        var rect = pre.getBoundingClientRect();
        var xch = (clientX - rect.left - entry.padLeft) / entry.chpx;
        best = Math.round(
          (xch - entry.lead - entry.colw / 2) / entry.colw
        );
        best = Math.max(0, Math.min(entry.times.length - 1, best));
      }}
      return best;
    }}
    // The moment at a pointer position in a roll: every note in the
    // nearest vertical slice. Shared by alt-clicks and alt-drags.
    function rollMoment(wrap, clientX) {{
      var rect = wrap.getBoundingClientRect();
      var frac = (clientX - rect.left) / rect.width;
      var t0 = parseFloat(wrap.dataset.start);
      var t1 = parseFloat(wrap.dataset.end);
      var t = t0 + frac * (t1 - t0);
      var nearest = null;
      wrap.querySelectorAll(".nr[data-start]").forEach(function (n) {{
        var d = Math.abs(parseFloat(n.dataset.start) - t);
        if (nearest === null || d < nearest.d) {{
          nearest = {{d: d, s: parseFloat(n.dataset.start)}};
        }}
      }});
      if (nearest === null) return null;
      var midis = [];
      wrap.querySelectorAll(".nr[data-start]").forEach(function (n) {{
        if (Math.abs(parseFloat(n.dataset.start) - nearest.s) <= 0.08) {{
          midis.push(parseInt(n.dataset.midi, 10));
        }}
      }});
      return {{key: nearest.s, midis: midis, time: t}};
    }}

    var rolls = document.querySelectorAll(".rollwrap[data-start]");
    rolls.forEach(function (wrap) {{
      wrap.addEventListener("click", function (e) {{
        var rect = wrap.getBoundingClientRect();
        var frac = (e.clientX - rect.left) / rect.width;
        var t0 = parseFloat(wrap.dataset.start);
        var t1 = parseFloat(wrap.dataset.end);
        var t = t0 + frac * (t1 - t0);
        if (e.altKey) {{
          var moment = rollMoment(wrap, e.clientX);
          if (moment) previewTone(moment.midis);
          return;
        }}
        seekOrLoop(e, t);
      }});
    }});

    // -- alt-drag audition: sweep the pointer to play through the song --
    // Mousedown starts and holds the notes under the pointer; crossing
    // into a new moment cross-fades to its notes; mouseup lets them ring
    // out. A drag over a single notehead plays just that note.
    var audition = null;
    function auditionMove(e) {{
      if (!audition) return;
      var key = null, midis = null;
      var target = e.target;
      var noteEl = target && target.closest
        ? target.closest(".nr[data-midi], .sn[data-midi]") : null;
      if (noteEl) {{
        key = "n" + noteEl.dataset.midi + "@" +
          (noteEl.dataset.start || "");
        midis = [parseInt(noteEl.dataset.midi, 10)];
      }} else if (audition.wrap) {{
        var moment = rollMoment(audition.wrap, e.clientX);
        if (moment) {{
          key = "c" + moment.key;
          midis = moment.midis;
        }}
      }} else if (audition.entry) {{
        var idx = wrapColumn(audition.entry, e.clientX);
        if (idx !== null) {{
          key = "c" + idx;
          midis = audition.entry.mids && audition.entry.mids[idx];
        }}
      }}
      if (!key || !midis || !midis.length) return;
      if (key === audition.lastKey) return;
      audition.lastKey = key;
      holdTones(midis);
    }}
    function beginAudition(state, e) {{
      e.preventDefault();
      audition = state;
      auditionMove(e);
    }}
    rolls.forEach(function (wrap) {{
      wrap.addEventListener("mousedown", function (e) {{
        if (!e.altKey || e.metaKey || e.ctrlKey) return;
        beginAudition({{wrap: wrap, lastKey: null}}, e);
      }});
    }});
    tabwraps.forEach(function (entry) {{
      entry.el.addEventListener("mousedown", function (e) {{
        if (!e.altKey || e.metaKey || e.ctrlKey) return;
        beginAudition({{entry: entry, lastKey: null}}, e);
      }});
    }});
    document.addEventListener("mousemove", auditionMove);
    document.addEventListener("mouseup", function () {{
      if (!audition) return;
      audition = null;
      suppressClick = true;
      releaseVoices(0.5);
    }});
    player.addEventListener("timeupdate", function () {{
      // Inside a loop region, wrap back to the start at the boundary.
      if (loop.b !== null && player.currentTime >= loop.b) {{
        player.currentTime = loop.a;
      }}
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
      if (karaoke) {{
        var sung = null;
        llines.forEach(function (l) {{
          if (t >= parseFloat(l.dataset.start) &&
              t < parseFloat(l.dataset.end)) sung = l;
        }});
        var text = sung ? sung.querySelector(".ltext").textContent : "";
        if (karaoke.textContent !== text) karaoke.textContent = text;
        karaoke.hidden = !text;
      }}
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
        if (t < w.t0 || t >= w.t1 || !w.times.length ||
            t < w.times[0]) {{
          w.line.style.display = "none";
          return;
        }}
        // seqPos glides between this column and the next in proportion
        // to time: smooth motion, exactly on each notehead at its onset.
        var pos = seqPos(w, t);
        w.line.style.display = "block";
        w.line.style.left = pos.v + pos.unit;
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
      if (e.code === "Escape") {{
        clearLoop();
        stopTones();
        return;
      }}
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.code === "Space") {{
        e.preventDefault();
        if (player.paused) player.play(); else player.pause();
      }} else if (e.code === "ArrowRight") {{
        e.preventDefault();
        var fwd = Math.min(
          player.duration || player.currentTime + 1,
          player.currentTime + 1
        );
        // Scrubbing respects an active loop: wrap at its end.
        if (loop.b !== null && fwd >= loop.b) fwd = loop.a;
        player.currentTime = fwd;
      }} else if (e.code === "ArrowLeft") {{
        e.preventDefault();
        var back = Math.max(0, player.currentTime - 1);
        if (loop.b !== null && back < loop.a) back = loop.a;
        player.currentTime = back;
      }} else if (e.code === "BracketLeft") {{
        e.preventDefault();
        nudgeSpeed(-1);
      }} else if (e.code === "BracketRight") {{
        e.preventDefault();
        nudgeSpeed(1);
      }}
    }});
  }})();
</script>
</body>
</html>
"""
