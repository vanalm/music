"""The Studio — a self-contained interactive play-along page.

``analyze`` writes ``report.html`` next to ``brief.md``. Double-click it and
the browser opens a two-pane practice room: the score on the left (one panel
per section, switchable between piano roll, guitar tab, grand-staff sheet
music, and chord chart, for the instruments or the sung melody), and a sticky
dock on the right (timeline, transport, the chord under the hand right now,
a lyric window that follows playback, the song's shapes).

How the page is put together:

* **The data travels as one payload.** ``build()`` reduces ``brief.json`` to
  ``window.SONG`` — sections, beat grid, chords with fingerings, every note
  as ``[start, end, midi, velocity]``, timed lyrics — and the page's script
  renders every chart from it client-side.
* **The renderers are shipped as package assets.** ``assets/report-lib.js``
  (chart renderers + word timing, a faithful port of the Python functions
  below) and ``assets/score-panel.js`` (the ``<score-panel>``,
  ``<song-timeline>``, and ``<chord-cards>`` custom elements) are inlined
  verbatim into the page at build time.
* **The Python renderers in this module are the reference implementations.**
  They define and test the musical behaviour (grouping windows, engraving
  rules, word-timing heuristics) that the JS ports mirror; a behaviour change
  starts here, in a test, and is then mirrored in the asset.

Constraints, deliberately:

* **One file, zero dependencies.** No frameworks, no CDN, no network
  requests. It works on an aeroplane over ``file://`` and never breaks
  because a host moved.
* **The audio travels with the page when it can.** A compact AAC preview is
  embedded as a data URI when ffmpeg is present and the result is small
  enough; otherwise it degrades to a relative path — and says so.
* **Sparse analysis → sparse page, never a broken one.** Every payload field
  is optional; a missing stage states how to get it.
"""

import base64
import html as _html
import json
import os
import subprocess
import tempfile
from pathlib import Path

from . import audio as audio_mod

#: Section label -> hue, so the timeline and chips are scannable at a glance.
_SECTION_HUES = {
    "intro": 210, "verse": 150, "chorus": 345, "bridge": 45,
    "solo": 280, "inst": 280, "break": 25, "outro": 265, "start": 200,
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


# -- reference renderers -----------------------------------------------------
# These draw nothing in the generated page any more — assets/report-lib.js
# holds the ports that do — but they remain the executable, tested
# specification of the musical behaviour. Change behaviour here first.


def chord_svg(positions, *, width=110, height=132):
    """Draw a chord box as inline SVG from voice_chord() positions.

    Strings are vertical lines (low E left), frets horizontal. Fretted notes
    are dots, open strings circles above the nut, unused strings an ``x``.
    """
    from .notes import note_name  # noqa: F401  (kept for parity with ports)

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
    from .notes import note_name

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
    from .notes import note_name

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


def word_segments(segments, *, onsets=None, snap=0.55):
    """Explode line-level Whisper segments into per-word timed segments.

    Whisper's default unit is the line: one start, one end, ten words. A
    lyric row built from lines parks a whole phrase at its first moment,
    which reads as misalignment. Real word timestamps (``words`` on a
    segment, produced when the transcription asked for them) pass through
    untouched; without them the line's span is divided among its words in
    proportion to their length.

    *onsets* — note starts from the voice transcription — sharpen the
    guess twice over: a line's words spread only across its *sung* span
    (Whisper pads line ends with instrumental silence, which otherwise
    drags the last words into the gap), and each word then snaps to the
    nearest vocal attack within *snap* seconds, in order, so words land
    on the moments the voice actually moved.
    """
    import bisect

    onsets = sorted(float(t) for t in onsets or [])
    out = []
    for line_no, seg in enumerate(segments or []):
        if seg.get("words"):
            # Tagged with their line so the row can alternate lanes per
            # phrase — words of one line must never interleave lanes.
            out.extend(dict(w, line=line_no) for w in seg["words"])
            continue
        words = str(seg.get("text") or "").split()
        if not words:
            continue
        try:
            start, end = float(seg["start"]), float(seg["end"])
        except (KeyError, TypeError, ValueError):
            continue
        line_on = onsets[
            bisect.bisect_left(onsets, start):bisect.bisect_right(onsets, end)
        ]
        sung_end = end
        if line_on:
            # The last attack plus a sung word's worth of ring-out.
            sung_end = min(end, max(line_on[-1] + 0.6, start + 0.5))
        span = max(sung_end - start, 0.0)
        weights = [len(w) + 1 for w in words]
        total = float(sum(weights))
        starts, t = [], start
        for weight in weights:
            starts.append(t)
            t += span * weight / total
        if line_on:
            floor = start
            for i, est in enumerate(starts):
                near = min(line_on, key=lambda o: abs(o - est))
                if abs(near - est) <= snap:
                    est = near
                starts[i] = max(est, floor)
                floor = starts[i] + 0.01
        for i, w in enumerate(words):
            w_end = starts[i + 1] if i + 1 < len(words) else sung_end
            out.append(
                {"start": round(starts[i], 2),
                 "end": round(max(w_end, starts[i] + 0.05), 2), "text": w,
                 "line": line_no}
            )
    return out


def _words_row(segments, start, end, *, times=None, xs=None, lead=2.0,
               colw=4.0):
    """The lyric, placed at its moment beneath a chart.

    Under the roll, each word sits at its horizontal time fraction; under
    sequence-spaced charts (staff, tab) it sits at the same x as the
    column sounding then, via :func:`_seq_x`.
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
        # Alternate lanes per lyric line: a phrase reads left to right on
        # one lane, and the next phrase takes the other, so adjacent
        # lines can overlap in time without printing over each other.
        spans.append(
            '<span class="word{lane}" style="left:{left}" data-start="{s}" '
            'data-end="{e}"><i>{text}</i></span>'.format(
                lane=" l1" if seg.get("line", 0) % 2 else "",
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
    from .notes import note_name

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


# -- page ------------------------------------------------------------------


def _asset(name):
    """Read an embeddable JS library shipped inside the package."""
    return (Path(__file__).parent / "assets" / name).read_text(
        encoding="utf-8"
    )


def _round2(x):
    return round(float(x), 2)


def song_payload(result, *, chords=None):
    """Reduce an ``analyze`` result to the page's one inline data payload.

    Everything the page renders comes from this dict, emitted as
    ``window.SONG``: the inlined ``report-lib.js`` draws the piano roll,
    tab, staff, and chord chart from exactly these fields. Notes compact
    to ``[start, end, midi, velocity]`` rows — smaller than the SVG
    strings they replaced.
    """
    from . import brief as brief_mod
    from . import notes as notes_mod

    stages = result.get("stages") or {}
    structure = (stages.get("structure") or {}).get("summary") or {}
    norm = (stages.get("normalize") or {}).get("summary") or {}
    lyrics = stages.get("lyrics") or {}
    if chords is None:
        chords = (stages.get("chords") or {}).get("chords")
    chords = chords or []
    voice_stage = stages.get("voice") or {}
    voice_notes = voice_stage.get("notes")

    def note_rows(notes):
        rows = []
        for e in notes or []:
            row = [_round2(e["start"]), _round2(e["end"]), int(e["midi"])]
            if e.get("velocity") is not None:
                row.append(int(e["velocity"]))
            rows.append(row)
        return rows

    def pos_rows(positions):
        return [
            [p["string"], p["fret"],
             notes_mod.STANDARD_TUNING[p["string"]] + p["fret"]]
            for p in positions or []
        ]

    def chord_rows(chord_list):
        out = []
        for c in chord_list or []:
            if c.get("start") is None or not c.get("symbol"):
                continue
            entry = {
                "symbol": c["symbol"], "start": _round2(c["start"]),
                "end": _round2(c.get("end") or c["start"]),
            }
            if c.get("shorthand"):
                entry["short"] = c["shorthand"]
            if c.get("positions"):
                entry["pos"] = pos_rows(c["positions"])
            out.append(entry)
        return out

    canon = {
        sym: {"short": short, "pos": pos_rows(positions)}
        for sym, short, positions in brief_mod.canonical_shapes(chords)
        if positions
    }
    duration = (
        structure.get("duration_seconds")
        or norm.get("duration_seconds") or 0
    )
    return {
        "title": result.get("title", "Untitled"),
        "bpm": structure.get("bpm"),
        "duration": duration,
        "codec": norm.get("codec"),
        "sample_rate": norm.get("sample_rate"),
        "channels": norm.get("channels"),
        "arrangement": structure.get("arrangement"),
        "missing": structure.get("missing") or [],
        "sections": structure.get("sections") or [],
        "beat_times": structure.get("beat_times") or [],
        "downbeat_times": structure.get("downbeat_times") or [],
        "lyric_segments": lyrics.get("segments") or [],
        "lyrics_text": lyrics.get("text"),
        "from_isolated_vocal": bool(lyrics.get("from_isolated_vocal")),
        "chords": chord_rows(chords),
        "notes": note_rows((stages.get("chords") or {}).get("notes")),
        "voice_notes": (
            note_rows(voice_notes) if voice_notes is not None else None
        ),
        "voice_chords": chord_rows(voice_stage.get("chords")),
        "canon": canon,
        "stems": [
            Path(f).name
            for f in (stages.get("stems") or {}).get("files") or []
        ],
        "skipped": result.get("skipped") or [],
        "questions": brief_mod.questions(result),
        "norm_file": (stages.get("normalize") or {}).get("file"),
    }


def _panels_html(payload, chord_list):
    """The score skeleton: one section element per panel group.

    Charts render client-side inside each ``<score-panel>``; this emits
    the static chrome around them — hue chip, range, chord mini, ▶ tones,
    the folded lick command — from the same grouping the payload carries.
    """
    from . import brief as brief_mod

    groups = brief_mod.progression_events(
        chord_list, payload.get("sections") or []
    )
    if not groups:
        # No chords yet: still one panel per labelled section (the roll
        # and staff draw from notes alone), or one whole-song panel.
        sections = payload.get("sections") or []
        if sections:
            groups = [
                (s["label"], float(s["start"]), float(s["end"]), [])
                for s in sections
            ]
        elif payload.get("duration"):
            groups = [(None, 0.0, float(payload["duration"]), [])]
    norm_file = payload.get("norm_file")
    parts = []
    for label, start, end, events in groups:
        hue = _SECTION_HUES.get(str(label or "").lower(), 200)
        syms = [sym for sym, _t0, _t1 in events]
        mini = " · ".join(syms[:8]) + (" …" if len(syms) > 8 else "")
        lick = ""
        if norm_file:
            cmd = "music-stack lick --input {} --start {} --end {}".format(
                norm_file, _clock(start), _clock(end)
            )
            lick = (
                '<details class="lickrow"><summary>re-transcribe this '
                "section note-perfectly</summary>"
                '<div class="lickbody"><code class="lick">{}</code>'
                '<button class="copy" type="button">copy</button>'
                "</div></details>"
            ).format(_esc(cmd))
        parts.append(
            '<section class="panel" data-start="{s}" data-end="{e}">'
            '<span class="nowbar"></span>'
            '<header class="phead">'
            '<span class="pchip" style="--h:{hue}">{label}</span>'
            '<span class="pnow">● now</span>'
            '<span class="prange">{c0}–{c1}</span>'
            '<span class="pmini">{mini}</span>'
            '<button class="tonesbtn" type="button">▶ tones</button>'
            "</header>"
            '<score-panel view="roll" source="inst" lyrics="synced" '
            'start="{s}" end="{e}"></score-panel>'
            "{lick}</section>".format(
                s=start, e=end, hue=hue, label=_esc(label or "all"),
                c0=_clock(start), c1=_clock(end), mini=_esc(mini), lick=lick,
            )
        )
    return "".join(parts)


def build(result, *, audio_path=None, chords=None):
    """Render an ``analyze`` result (the ``brief.json`` shape) as one page."""
    stages = result.get("stages") or {}
    if chords is None:
        chord_list = (stages.get("chords") or {}).get("chords") or []
    else:
        chord_list = chords or []
    payload = song_payload(result, chords=chord_list)

    # -- audio ------------------------------------------------------------
    audio_note = ""
    if audio_path:
        data_uri, note = preview_audio(audio_path)
        if data_uri:
            audio_html = (
                '<audio id="player" preload="metadata" '
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
                '<audio id="player" preload="metadata" src="{src}"></audio>'
            ).format(src=_esc(audio_src))
            audio_note = (
                '<p class="note">Audio is not embedded ({why}); playback '
                "needs this file to stay next to its project folder.</p>"
            ).format(why=_esc(note))
    else:
        audio_html = ""
        audio_note = '<p class="note">No audio available for playback.</p>'

    # -- header facts -------------------------------------------------------
    facts = []
    if payload["bpm"]:
        facts.append("<b>{}</b> BPM".format(_esc(payload["bpm"])))
    if payload["duration"]:
        facts.append(_clock(payload["duration"]))
    if payload["sample_rate"]:
        try:
            facts.append("{:g} kHz".format(float(payload["sample_rate"]) / 1000))
        except (TypeError, ValueError):
            pass
    facts_html = " · ".join(facts)

    # -- control row ---------------------------------------------------------
    vpills = "".join(
        '<button type="button" class="pill vpill{act}" data-view="{k}">'
        "{label}</button>".format(
            act=" on" if k == "roll" else "", k=k, label=label
        )
        for k, label in (
            ("roll", "Piano roll"), ("tab", "Guitar tab"),
            ("staff", "Sheet music"), ("chart", "Chord chart"),
        )
    )
    controls = '<div class="tray">{}</div>'.format(vpills)
    if payload["voice_notes"] is not None:
        controls += '<div class="tray">{}</div>'.format(
            "".join(
                '<button type="button" class="pill spill{act}" '
                'data-source="{k}">{label}</button>'.format(
                    act=" on" if k == "inst" else "", k=k, label=label
                )
                for k, label in (("inst", "Instrument"), ("voice", "Voice"))
            )
        )
    controls += (
        '<span id="loopbadge" class="loopbadge" hidden></span>'
        '<span class="hint">click = move · drag = scrub · '
        "⌘-click ×2 = loop · ⌥ = hear</span>"
    )

    # -- structure / timeline notes ------------------------------------------
    structure_note = ""
    if not payload["sections"]:
        structure_note = (
            '<p class="note">No structure analysis yet — install allin1 '
            "(<code>music-stack local doctor</code> has the steps) and "
            "re-run <code>music-stack analyze</code>.</p>"
        )
    missing_html = ""
    if payload["missing"]:
        missing_html = '<p class="missing">not present yet: {}</p>'.format(
            _esc(", ".join(payload["missing"]))
        )

    # -- dock: lyric block, shapes, stems -------------------------------------
    if payload["lyric_segments"]:
        provenance = (
            "transcribed from the isolated vocal"
            if payload["from_isolated_vocal"]
            else "transcribed from the full mix — expect errors where "
                 "instruments mask the vocal"
        )
        lyric_block = (
            '<div class="dhead">Lyric — follows playback</div>'
            '<p class="note">{}</p>'
            '<div id="lyricwin" class="lyricwin"></div>'.format(
                _esc(provenance)
            )
        )
    elif payload["lyrics_text"]:
        provenance = (
            "transcribed from the isolated vocal"
            if payload["from_isolated_vocal"]
            else "transcribed from the full mix — expect errors where "
                 "instruments mask the vocal"
        )
        lyric_block = (
            '<div class="dhead">Lyrics as sung</div>'
            '<p class="note">{}</p>'
            '<pre class="lyrics">{}</pre>'.format(
                _esc(provenance), _esc(payload["lyrics_text"])
            )
        )
    else:
        lyric_block = (
            '<div class="dhead">Lyric</div>'
            '<p class="note">No lyrics transcribed — install a Whisper '
            "(<code>music-stack local doctor</code>) and re-run.</p>"
        )

    shapes_html = ""
    if payload["canon"]:
        symbols = sorted(payload["canon"])
        shapes_html = (
            '<div class="card"><div class="dhead-row">'
            '<span class="dhead">Shapes in this song</span>'
            '<span class="dcount">{n} total</span></div>'
            '<div class="shapegrid"><chord-cards id="shapecards" '
            'symbols="{syms}"></chord-cards></div></div>'.format(
                n=len(symbols), syms=_esc(",".join(symbols[:6])),
            )
        )

    stems_html = ""
    if payload["stems"]:
        stems_html = (
            '<div class="card stemsrow"><span>Stems</span>'
            '<span class="mono">{}</span></div>'.format(
                _esc(" · ".join(
                    Path(f).stem for f in payload["stems"]
                ))
            )
        )

    now_card = ""
    if payload["chords"]:
        now_card = (
            '<div class="card nowcard">'
            '<div class="dhead-row"><span class="dhead accent">Now playing'
            '</span><span id="nowchip" class="pchip" style="--h:200">—</span>'
            '<span id="nowrange" class="dcount"></span></div>'
            '<div class="nowgrid">'
            '<div class="nowgripbox"><chord-cards id="nowgrip" symbols="" '
            'current=""></chord-cards></div>'
            '<div><div id="nowsym" class="nowsym">—</div>'
            '<div id="nowshort" class="nowshort"></div>'
            '<div id="nextchords" class="nextchords"></div></div>'
            "</div></div>"
        )

    # -- questions ------------------------------------------------------------
    questions_html = "".join(
        '<p class="question">{}</p>'.format(_esc(q))
        for q in payload["questions"]
    )

    skipped_html = ""
    if payload["skipped"]:
        skipped_html = (
            '<p class="note">Stages skipped (tool not installed): {}. Run '
            "<code>music-stack local doctor</code>.</p>".format(
                _esc(", ".join(payload["skipped"]))
            )
        )

    # A "<" inside the JSON could open a tag (or "</script>" could end the
    # block early); \\u003c decodes to the same character but stays inert
    # in HTML.
    payload_json = json.dumps(payload, separators=(",", ":")).replace(
        "<", "\\u003c"
    )

    page = _TEMPLATE
    for token, value in (
        ("@@TITLE@@", _esc(payload["title"])),
        ("@@FACTS@@", facts_html),
        ("@@CONTROLS@@", controls),
        ("@@STRUCTURE_NOTE@@", structure_note),
        ("@@MISSING@@", missing_html),
        ("@@PANELS@@", _panels_html(payload, chord_list)),
        ("@@QUESTIONS@@", questions_html),
        ("@@SKIPPED@@", skipped_html),
        ("@@AUDIO@@", audio_html),
        ("@@AUDIO_NOTE@@", audio_note),
        ("@@NOW_CARD@@", now_card),
        ("@@LYRIC_BLOCK@@", lyric_block),
        ("@@SHAPES@@", shapes_html),
        ("@@STEMS@@", stems_html),
        ("@@PAYLOAD@@", payload_json),
        ("@@REPORT_LIB@@", _asset("report-lib.js")),
        ("@@SCORE_PANEL@@", _asset("score-panel.js")),
        ("@@APP_JS@@", _APP_JS),
    ):
        page = page.replace(token, value)
    return page


def write(result, project_dir, *, audio_path=None, chords=None):
    """Write ``report.html`` into *project_dir*; returns its path."""
    project_dir = Path(project_dir)
    out = project_dir / "report.html"
    out.write_text(
        build(result, audio_path=audio_path, chords=chords), encoding="utf-8"
    )
    return out


# The studio app: the transport adapter around the real <audio> element plus
# all page state (view/source pills, loop, speed, tones, theme, dock cards).
# Plain vanilla JS — inlined after the two library scripts.
_APP_JS = r"""
(function () {
  var root = document.getElementById("studio-root");
  var KEY = "music-studio-v1";
  var saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
  var state = {
    view: saved.view || "roll",
    source: saved.source || "inst",
    rate: 1,
    theme: saved.theme || "light",
    loopA: null, loopB: null, pendingA: null
  };
  var VIEWS = ["roll", "tab", "staff", "chart"];
  if (VIEWS.indexOf(state.view) < 0) state.view = "roll";
  if (!document.querySelector('.spill[data-source="voice"]')) {
    state.source = "inst";
  }
  root.setAttribute("data-theme", state.theme);
  var themeBtn = document.getElementById("themebtn");
  function themeLabel() {
    return state.theme === "light" ? "◐ dark" : "◑ light";
  }
  if (themeBtn) {
    themeBtn.textContent = themeLabel();
    themeBtn.addEventListener("click", function () {
      state.theme = state.theme === "light" ? "dark" : "light";
      root.setAttribute("data-theme", state.theme);
      themeBtn.textContent = themeLabel();
      persist();
    });
  }
  var audio = document.getElementById("player");
  if (audio && !audio.getAttribute("src")) audio = null;
  var SONG = null, L = null;

  function persist() {
    try {
      localStorage.setItem(KEY, JSON.stringify({
        t: audio ? audio.currentTime : 0,
        rate: state.rate, view: state.view, source: state.source,
        theme: state.theme
      }));
    } catch (e) {}
  }

  // -- view / source pills drive every panel via attributes ---------------
  function applyPanes() {
    document.querySelectorAll("score-panel").forEach(function (sp) {
      sp.setAttribute("view", state.view);
      sp.setAttribute("source", state.source);
    });
    document.querySelectorAll(".vpill").forEach(function (b) {
      b.classList.toggle("on", b.dataset.view === state.view);
    });
    document.querySelectorAll(".spill").forEach(function (b) {
      b.classList.toggle("on", b.dataset.source === state.source);
    });
  }
  document.querySelectorAll(".vpill").forEach(function (b) {
    b.addEventListener("click", function () {
      state.view = b.dataset.view;
      applyPanes(); persist();
      setTimeout(pushFine, 80);
    });
  });
  document.querySelectorAll(".spill").forEach(function (b) {
    b.addEventListener("click", function () {
      state.source = b.dataset.source;
      applyPanes(); persist();
      setTimeout(pushFine, 80);
    });
  });

  // -- A/B loop -------------------------------------------------------------
  function applyLoop() {
    var v = state.loopA != null && state.loopB != null
      ? state.loopA + "," + state.loopB : "";
    document.querySelectorAll("score-panel, song-timeline").forEach(
      function (el) {
        if (v) el.setAttribute("loop", v);
        else el.removeAttribute("loop");
      }
    );
    var badge = document.getElementById("loopbadge");
    if (badge && L) {
      var text = "";
      if (state.loopB != null) {
        text = "⟳ looping " + L.clock(state.loopA) + "–" +
          L.clock(state.loopB) + " · esc clears";
      } else if (state.pendingA != null) {
        text = "⟳ loop start " + L.clock(state.pendingA) +
          " — ⌘-click the end";
      }
      badge.textContent = text;
      badge.hidden = !text;
    }
  }
  function clearLoop() {
    state.loopA = state.loopB = state.pendingA = null;
    applyLoop();
  }
  document.addEventListener("sp-loop-point", function (e) {
    var t = e.detail.t;
    if (state.pendingA == null || state.loopB != null) {
      state.pendingA = t;
      state.loopA = state.loopB = null;
    } else {
      state.loopA = Math.min(state.pendingA, t);
      state.loopB = Math.max(state.pendingA, t);
      state.pendingA = null;
    }
    applyLoop();
  });

  // -- transport: the real <audio> element ---------------------------------
  var playBtn = document.getElementById("playbtn");
  var clockEl = document.getElementById("clocknow");
  function setPlayIcon() {
    if (playBtn) {
      playBtn.textContent = audio && !audio.paused ? "❚❚" : "▶";
    }
  }
  if (playBtn) {
    if (!audio) {
      playBtn.disabled = true;
      playBtn.title = "no audio available";
    } else {
      playBtn.addEventListener("click", function () {
        if (audio.paused) audio.play(); else audio.pause();
      });
    }
  }
  document.addEventListener("sp-seek", function (e) {
    if (audio) audio.currentTime = e.detail.t;
  });
  var wasPaused = false;
  document.addEventListener("sp-scrub-start", function () {
    if (!audio) return;
    wasPaused = audio.paused;
    if (wasPaused) audio.play();
  });
  document.addEventListener("sp-scrub", function (e) {
    if (audio) audio.currentTime = e.detail.t;
  });
  document.addEventListener("sp-scrub-end", function () {
    if (audio && wasPaused) audio.pause();
  });

  function now() { return audio ? audio.currentTime : 0; }

  var lastPanelIdx = -1, lastCoarse = -10;
  function pushFine() {
    var t = now();
    if (audio && state.loopB != null && t >= state.loopB) {
      audio.currentTime = state.loopA;
      t = state.loopA;
    }
    document.querySelectorAll("score-panel").forEach(function (sp) {
      if (sp.update) sp.update(t, { follow: true });
    });
    document.querySelectorAll("song-timeline").forEach(function (tl) {
      if (tl.update) tl.update(t);
    });
    if (clockEl && L && SONG) {
      clockEl.innerHTML = L.clock(t) +
        ' <span class="dim">/ ' + L.clock(SONG.duration) + "</span>";
    }
    if (Math.abs(t - lastCoarse) > 0.24) {
      lastCoarse = t;
      coarse(t);
    }
  }
  // Throttled (~4 Hz): karaoke line, lyric window, now-chord card,
  // current-section chip and panel accents — recomputed from SONG.
  function coarse(t) {
    if (!SONG || !L) return;
    var kar = document.getElementById("karaoke");
    if (kar) {
      var seg = null;
      SONG.lyricSegments.forEach(function (g) {
        if (t >= g.start && t < g.end) seg = g;
      });
      var text = seg ? "“" + seg.text + "”" : "";
      if (kar.textContent !== text) kar.textContent = text;
    }
    var win = document.getElementById("lyricwin");
    if (win && SONG.lyricSegments.length) {
      var idx = -1, i;
      for (i = 0; i < SONG.lyricSegments.length; i++) {
        if (t < SONG.lyricSegments[i].end) { idx = i; break; }
      }
      if (idx < 0) idx = SONG.lyricSegments.length;
      var from = Math.max(0, idx - 1);
      win.innerHTML = SONG.lyricSegments.slice(from, from + 4)
        .map(function (g) {
          var cur = t >= g.start && t < g.end;
          return '<div class="lline' + (cur ? " now" : "") +
            '" data-start="' + g.start + '">' + L.esc(g.text) + "</div>";
        }).join("");
    }
    var cur = null, lastBefore = null;
    SONG.chords.forEach(function (c) {
      if (c.start <= t) {
        lastBefore = c;
        if (c.end > t) cur = c;
      }
    });
    var ch = cur || lastBefore;
    var sym = ch ? ch.symbol : "—";
    var symEl = document.getElementById("nowsym");
    if (symEl && symEl.textContent !== sym) {
      symEl.textContent = sym;
      var canon = SONG.canon[sym];
      var shortEl = document.getElementById("nowshort");
      if (shortEl) shortEl.textContent = canon && canon.short ? canon.short : "";
      var grip = document.getElementById("nowgrip");
      if (grip) {
        grip.setAttribute("symbols", ch ? sym : "");
        grip.setAttribute("current", sym);
      }
    }
    var nextEl = document.getElementById("nextchords");
    if (nextEl) {
      var g2 = null;
      SONG.panels.forEach(function (p) {
        if (t >= p.start && t < p.end) g2 = p;
      });
      var up = g2 ? g2.events.filter(function (ev) { return ev[1] > t; })
        .slice(0, 4).map(function (ev) { return ev[0]; }) : [];
      nextEl.textContent = up.length ? "next: " + up.join(" · ") : "";
    }
    var sec = null;
    SONG.sections.forEach(function (x) {
      if (x.seconds > 1.5 && t >= x.start && t < x.end) sec = x;
    });
    var chip = document.getElementById("nowchip");
    if (chip) {
      chip.textContent = sec ? sec.label : "—";
      chip.style.setProperty(
        "--h",
        sec ? (L.SECTION_HUES[String(sec.label).toLowerCase()] || 200) : 200
      );
      var rng = document.getElementById("nowrange");
      if (rng) {
        rng.textContent = sec
          ? L.clock(sec.start) + "–" + L.clock(sec.end) : "";
      }
    }
    var panels = document.querySelectorAll("section.panel");
    var nowIdx = -1;
    panels.forEach(function (el, pi) {
      var on = t >= parseFloat(el.dataset.start) &&
        t < parseFloat(el.dataset.end);
      el.classList.toggle("now", on);
      if (on) nowIdx = pi;
    });
    if (audio && !audio.paused && nowIdx >= 0 && nowIdx !== lastPanelIdx) {
      lastPanelIdx = nowIdx;
      var r = panels[nowIdx].getBoundingClientRect();
      if (r.top < 90 || r.bottom > window.innerHeight) {
        window.scrollTo({
          top: r.top + window.scrollY - 120, behavior: "smooth"
        });
      }
    }
  }
  var winEl = document.getElementById("lyricwin");
  if (winEl) {
    winEl.addEventListener("click", function (e) {
      var l = e.target.closest ? e.target.closest(".lline") : null;
      if (l && audio) audio.currentTime = parseFloat(l.dataset.start);
    });
  }

  if (audio) {
    audio.addEventListener("timeupdate", pushFine);
    audio.addEventListener("play", setPlayIcon);
    audio.addEventListener("pause", function () {
      setPlayIcon();
      persist();
    });
    // Smooth line between native timeupdates while playing.
    (function raf() {
      if (!audio.paused) pushFine();
      requestAnimationFrame(raf);
    })();
  }

  // -- speed: time-stretch without pitch shift ------------------------------
  var RATES = [0.5, 0.65, 0.75, 0.85, 1];
  var rateBtn = document.getElementById("ratebtn");
  var rateMenu = document.getElementById("ratemenu");
  function setRate(r) {
    state.rate = r;
    if (audio) {
      audio.playbackRate = r;
      audio.preservesPitch = true;
      audio.webkitPreservesPitch = true;
    }
    if (rateBtn) {
      rateBtn.textContent = (r === 1 ? "1" : String(r)) + "× · keys ▾";
    }
    document.querySelectorAll(".ratepill").forEach(function (b) {
      b.classList.toggle("on", parseFloat(b.dataset.rate) === r);
    });
    persist();
  }
  if (rateBtn && rateMenu) {
    rateBtn.addEventListener("click", function () {
      rateMenu.hidden = !rateMenu.hidden;
    });
  }
  document.querySelectorAll(".ratepill").forEach(function (b) {
    b.addEventListener("click", function () {
      setRate(parseFloat(b.dataset.rate));
    });
  });

  // -- per-section tones: the transcription as synth, at tempo -------------
  var tones = { idx: -1, btn: null, nodes: [], timer: null };
  function stopTones() {
    if (tones.timer) clearTimeout(tones.timer);
    var t0 = 0;
    try { t0 = L ? L.ctx().currentTime : 0; } catch (e) {}
    tones.nodes.forEach(function (v) {
      try {
        v.gain.gain.cancelScheduledValues(t0);
        v.gain.gain.setValueAtTime(Math.max(v.gain.gain.value, 0.0001), t0);
        v.gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.15);
        v.osc.stop(t0 + 0.2);
      } catch (e) {}
    });
    tones.nodes = [];
    if (tones.btn) {
      tones.btn.textContent = "▶ tones";
      tones.btn.classList.remove("on");
    }
    tones.idx = -1;
    tones.btn = null;
    tones.timer = null;
  }
  function playTones(i, btn) {
    if (!SONG || !L) return;
    if (tones.idx === i) { stopTones(); return; }
    stopTones();
    var sec = document.querySelectorAll("section.panel")[i];
    if (!sec) return;
    var s = parseFloat(sec.dataset.start), e = parseFloat(sec.dataset.end);
    var pool = state.source === "voice" ? (SONG.voiceNotes || []) : SONG.notes;
    var notes = pool.filter(function (n) { return n.start < e && n.end > s; });
    if (!notes.length) return;
    var ac;
    try { ac = L.ctx(); } catch (err) { return; }
    var bus = ac.createDynamicsCompressor();
    bus.connect(ac.destination);
    var rate = state.rate || 1;
    var first = Infinity;
    notes.forEach(function (n) { first = Math.min(first, n.start); });
    var base = ac.currentTime + 0.08, last = 0;
    notes.forEach(function (n) {
      var at = base + (n.start - first) / rate;
      var dur = Math.max(n.end - n.start, 0.08) / rate;
      var osc = ac.createOscillator();
      var filter = ac.createBiquadFilter();
      var gain = ac.createGain();
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
      tones.nodes.push({ osc: osc, gain: gain });
      last = Math.max(last, (n.start - first) / rate + dur);
    });
    tones.idx = i;
    tones.btn = btn;
    btn.textContent = "■ stop";
    btn.classList.add("on");
    tones.timer = setTimeout(stopTones, (last + 0.5) * 1000);
  }
  document.querySelectorAll(".tonesbtn").forEach(function (btn, i) {
    btn.addEventListener("click", function () { playTones(i, btn); });
  });

  // -- copy the lick command -------------------------------------------------
  document.querySelectorAll(".copy").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var code = btn.parentElement.querySelector(".lick");
      if (!code || !navigator.clipboard) return;
      navigator.clipboard.writeText(code.textContent).then(function () {
        btn.textContent = "copied";
        setTimeout(function () { btn.textContent = "copy"; }, 1400);
      });
    });
  });

  // -- keyboard ---------------------------------------------------------------
  document.addEventListener("keydown", function (e) {
    if (e.target && /INPUT|TEXTAREA/.test(e.target.tagName)) return;
    if (e.code === "Escape") {
      clearLoop();
      stopTones();
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (!audio) return;
    if (e.code === "Space") {
      e.preventDefault();
      if (audio.paused) audio.play(); else audio.pause();
    } else if (e.code === "ArrowRight") {
      e.preventDefault();
      var fwd = Math.min(
        audio.duration || audio.currentTime + 1, audio.currentTime + 1
      );
      // Scrubbing respects an active loop: wrap at its end.
      if (state.loopB != null && fwd >= state.loopB) fwd = state.loopA;
      audio.currentTime = fwd;
    } else if (e.code === "ArrowLeft") {
      e.preventDefault();
      var back = Math.max(0, audio.currentTime - 1);
      if (state.loopB != null && back < state.loopA) back = state.loopA;
      audio.currentTime = back;
    } else if (e.code === "BracketLeft" || e.code === "BracketRight") {
      e.preventDefault();
      var ri = RATES.indexOf(state.rate);
      if (ri < 0) ri = RATES.length - 1;
      setRate(RATES[Math.max(0, Math.min(
        RATES.length - 1, ri + (e.code === "BracketRight" ? 1 : -1)
      ))]);
    }
  });

  // -- boot ---------------------------------------------------------------------
  applyPanes();
  var boot = setInterval(function () {
    if (!window.ReportLib) return;
    clearInterval(boot);
    L = window.ReportLib;
    L.loadSong().then(function (song) {
      SONG = song;
      applyPanes();
      var r0 = saved.rate && RATES.indexOf(saved.rate) >= 0 ? saved.rate : 1;
      setRate(r0);
      if (audio && saved.t && isFinite(saved.t) && SONG.duration) {
        var t0 = Math.min(saved.t, Math.max(0, SONG.duration - 1));
        var restore = function () {
          try { audio.currentTime = t0; } catch (err) {}
        };
        if (audio.readyState >= 1) restore();
        else audio.addEventListener("loadedmetadata", restore, { once: true });
      }
      pushFine();
      coarse(now());
      setInterval(persist, 2500);
    });
  }, 25);
})();
"""


# The static page chrome: the Studio layout — score left, sticky practice
# dock right. Tokens (@@…@@) are replaced by build(); braces are plain
# braces, so the two inlined JS libraries need no escaping.
_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>@@TITLE@@</title>
<style>
  /* Design tokens — the one "now/interactive" color is --c-accent; the
     notes themselves are --c-note. Dark theme flips via [data-theme]. */
  .root {
    --c-bg:#f6f3ec; --c-card:#fdfbf7; --c-panel:#efe9db; --c-ink:#221d15;
    --c-muted:#8b8272; --c-line:#e4ddca; --c-accent:#b4502e;
    --c-note:#46607e;
    --sp-ink:var(--c-ink); --sp-muted:var(--c-muted);
    --sp-line:var(--c-line); --sp-accent:var(--c-accent);
    --sp-note:var(--c-note); --sp-grid:#ece4d2; --sp-staffline:#b6ad97;
    --sp-chart-bg:var(--c-card); --sp-chip-bg:var(--c-panel);
    --f-serif:'New York',ui-serif,Georgia,'Times New Roman',serif;
    --f-sans:-apple-system,BlinkMacSystemFont,'SF Pro Text','Segoe UI',
      system-ui,sans-serif;
    --f-mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace;
    --sp-serif:var(--f-serif); --sp-sans:var(--f-sans);
    --sp-mono:var(--f-mono);
    background:var(--c-bg); color:var(--c-ink);
    font:15px/1.55 var(--f-sans); min-height:100vh;
    -webkit-font-smoothing:antialiased;
  }
  .root[data-theme="dark"] {
    --c-bg:#171511; --c-card:#1f1c16; --c-panel:#262218; --c-ink:#ece5d4;
    --c-muted:#9a927e; --c-line:#353024; --c-accent:#e07a50;
    --c-note:#93add0; --sp-grid:#2e2a20; --sp-staffline:#57503f;
    --sp-chart-bg:#1c1914;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:#171511; }
  .studio {
    display:grid; grid-template-columns:minmax(0,1fr) 352px;
    min-height:100vh; max-width:1500px; margin:0 auto;
  }
  main { min-width:0; padding:20px 26px 46px; }
  .shead { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
  .shead h1 {
    font:600 23px/1.1 var(--f-serif); letter-spacing:-.01em; margin:0;
  }
  .facts {
    font:500 11.5px var(--f-mono); color:var(--c-muted);
    font-variant-numeric:tabular-nums;
  }
  .facts b { color:var(--c-ink); font-weight:600; }
  .themebtn {
    margin-left:auto; border:1px solid var(--c-line); background:transparent;
    color:var(--c-muted); border-radius:999px; padding:3px 11px;
    font:600 10.5px var(--f-sans); cursor:pointer;
  }
  .controls {
    display:flex; align-items:center; gap:10px; margin-top:14px;
    flex-wrap:wrap;
  }
  .tray {
    display:inline-flex; gap:2px; background:var(--c-panel);
    border:1px solid var(--c-line); border-radius:9px; padding:2px;
  }
  .pill {
    border:0; background:transparent; padding:5px 12px; border-radius:7px;
    font:500 12.5px var(--f-sans); color:var(--c-muted); cursor:pointer;
  }
  .pill.on {
    background:var(--c-card); color:var(--c-ink); font-weight:600;
    box-shadow:0 1px 2px rgb(20 16 8 / .12);
  }
  .hint {
    margin-left:auto; font:500 11.5px var(--f-sans); color:var(--c-muted);
  }
  .loopbadge { font:600 12px var(--f-sans); color:var(--c-accent); }
  .note { font-size:.84rem; color:var(--c-muted); }
  .missing { font:500 12px var(--f-sans); color:#a2401f; margin:.4rem 0 0; }
  code {
    background:var(--c-panel); padding:.1rem .35rem; border-radius:5px;
    font:500 .85em var(--f-mono);
  }

  /* -- the score ---------------------------------------------------------- */
  section.panel {
    position:relative; margin-top:20px; padding-top:18px;
    border-top:1px solid var(--c-line);
  }
  section.panel .nowbar {
    display:none; position:absolute; left:-26px; top:20px; bottom:2px;
    width:3px; border-radius:2px; background:var(--c-accent);
  }
  section.panel.now .nowbar { display:block; }
  section.panel .pnow {
    display:none; font:600 11px var(--f-sans); color:var(--c-accent);
  }
  section.panel.now .pnow { display:inline; }
  .phead {
    display:flex; align-items:baseline; gap:10px; flex-wrap:wrap;
    margin-bottom:9px;
  }
  .pchip {
    font:700 11px var(--f-sans); letter-spacing:.06em;
    text-transform:uppercase; color:hsl(var(--h) 30% 33%);
    background:hsl(var(--h) 32% 92%);
    border:1px solid hsl(var(--h) 26% 82%); border-radius:6px;
    padding:2px 9px;
  }
  .root[data-theme="dark"] .pchip {
    color:hsl(var(--h) 45% 75%); background:hsl(var(--h) 25% 18%);
    border-color:hsl(var(--h) 20% 30%);
  }
  .prange {
    font:500 12px var(--f-mono); color:var(--c-muted);
    font-variant-numeric:tabular-nums;
  }
  .pmini {
    font:500 12px var(--f-sans); color:var(--c-muted); flex:1;
    min-width:120px; overflow:hidden; text-overflow:ellipsis;
    white-space:nowrap;
  }
  .tonesbtn {
    border:1px solid var(--c-accent); background:transparent;
    color:var(--c-accent); border-radius:999px; padding:2px 10px;
    font:600 11px var(--f-sans); cursor:pointer;
  }
  .tonesbtn.on { background:var(--c-accent); color:#fff; }
  score-panel { display:block; min-height:40px; }
  .lickrow { margin-top:7px; }
  .lickrow summary {
    font:500 11px var(--f-sans); color:var(--c-muted); cursor:pointer;
  }
  .lickrow summary:hover { color:var(--c-accent); }
  .lickbody { display:flex; gap:8px; align-items:center; margin-top:5px; }
  .lickbody .lick {
    flex:1; overflow-x:auto; white-space:nowrap;
    font:500 11px var(--f-mono); color:var(--c-muted);
    background:var(--c-panel); padding:5px 9px; border-radius:7px;
  }
  .copy {
    border:1px solid var(--c-line); background:var(--c-card);
    color:var(--c-muted); border-radius:7px; padding:4px 10px;
    font:600 11px var(--f-sans); cursor:pointer;
  }
  .copy:hover { border-color:var(--c-accent); color:var(--c-accent); }
  .questions {
    margin-top:28px; padding:15px 17px; border-radius:14px;
    border:1px solid color-mix(in srgb, var(--c-accent) 35%, var(--c-line));
    background:color-mix(in srgb, var(--c-accent) 4%, var(--c-card));
  }
  .questions h3 {
    font:600 10.5px var(--f-sans); letter-spacing:.12em;
    text-transform:uppercase; color:var(--c-muted); margin:0;
  }
  .question {
    font:italic 400 14.5px/1.5 var(--f-serif); margin:7px 0 0;
  }

  /* -- the dock ------------------------------------------------------------ */
  aside {
    border-left:1px solid var(--c-line);
    background:color-mix(in srgb, var(--c-card) 55%, var(--c-bg));
    min-width:0;
  }
  .dock {
    position:sticky; top:0; max-height:100vh; overflow:auto;
    padding:16px 16px 22px; display:flex; flex-direction:column; gap:13px;
  }
  .card {
    border:1px solid var(--c-line); border-radius:14px;
    background:var(--c-card); padding:13px;
    box-shadow:0 1px 2px rgb(24 18 8 / .05);
  }
  .dhead {
    font:600 10px var(--f-sans); letter-spacing:.12em;
    text-transform:uppercase; color:var(--c-muted);
  }
  .dhead.accent { color:var(--c-accent); }
  .dhead-row {
    display:flex; align-items:center; gap:8px; justify-content:space-between;
  }
  .dcount {
    font:500 10.5px var(--f-mono); color:var(--c-muted);
    font-variant-numeric:tabular-nums;
  }
  #studio-timeline { --st-h:38px; --st-radius:8px; --st-font:.58rem; }
  .transport {
    display:flex; align-items:center; gap:10px; margin-top:10px;
  }
  #playbtn {
    width:42px; height:42px; border-radius:50%;
    border:1.5px solid var(--c-accent); color:var(--c-accent);
    background:color-mix(in srgb, var(--c-accent) 8%, transparent);
    font-size:15px; cursor:pointer; flex:none;
  }
  #playbtn:disabled { opacity:.4; cursor:default; }
  #clocknow {
    font:600 15px var(--f-mono); font-variant-numeric:tabular-nums;
  }
  #clocknow .dim { color:var(--c-muted); font-weight:500; }
  #ratebtn {
    margin-left:auto; border:1px solid var(--c-line); background:transparent;
    color:var(--c-muted); border-radius:8px; padding:4px 10px;
    font:600 11px var(--f-sans); cursor:pointer;
  }
  #ratemenu { margin-top:10px; padding-top:10px;
    border-top:1px solid var(--c-line); }
  .ratepills { display:flex; gap:5px; margin-top:7px; flex-wrap:wrap; }
  .ratepill {
    border:1px solid var(--c-line); background:transparent;
    color:var(--c-muted); border-radius:999px; padding:3px 10px;
    font:600 11.5px var(--f-mono); cursor:pointer;
  }
  .ratepill.on {
    border-color:var(--c-accent); color:var(--c-accent);
    background:color-mix(in srgb, var(--c-accent) 10%, transparent);
    font-weight:700;
  }
  .keysgrid {
    display:grid; grid-template-columns:auto 1fr; gap:4px 10px;
    margin-top:11px; font:500 11px var(--f-sans); color:var(--c-muted);
    align-items:baseline;
  }
  kbd {
    border:1px solid var(--c-line); border-bottom-width:2px;
    border-radius:5px; padding:0 5px; font:600 10px var(--f-mono);
    background:var(--c-panel); color:var(--c-ink);
  }
  #karaoke {
    margin-top:9px; padding-top:9px; border-top:1px solid var(--c-line);
    font:italic 500 13.5px/1.4 var(--f-serif); text-align:center;
    min-height:19px;
  }
  .nowcard {
    border-color:color-mix(in srgb, var(--c-accent) 40%, var(--c-line));
  }
  .nowgrid {
    display:grid; grid-template-columns:96px 1fr; gap:12px;
    align-items:center; margin-top:9px;
  }
  .nowgripbox { --cc-min:92px; --cc-box:92px; }
  .nowsym { font:600 28px/1 var(--f-serif); color:var(--c-accent); }
  .nowshort {
    font:500 11px var(--f-mono); color:var(--c-muted); margin-top:3px;
  }
  .nextchords {
    font:500 11.5px var(--f-sans); color:var(--c-muted); margin-top:6px;
  }
  .lyricwin {
    display:flex; flex-direction:column; gap:5px; margin-top:8px;
    font:400 12.5px/1.4 var(--f-sans); min-height:4.2em;
  }
  .lline { color:var(--c-muted); cursor:pointer; }
  .lline:hover { color:var(--c-accent); }
  .lline.now {
    color:var(--c-accent); font-weight:600;
    border-left:2.5px solid var(--c-accent); padding-left:8px;
    margin-left:-10.5px;
  }
  .lyrics {
    white-space:pre-wrap; font:400 12.5px/1.5 var(--f-sans); margin:8px 0 0;
  }
  .shapegrid { margin-top:9px; --cc-min:70px; --cc-box:70px; --cc-gap:.45rem; }
  .stemsrow {
    display:flex; justify-content:space-between; border-radius:10px;
    padding:8px 12px; font:500 12px var(--f-sans); color:var(--c-muted);
  }
  .stemsrow .mono { font:500 11px var(--f-mono); }
  .about {
    font:500 11px/1.5 var(--f-sans); color:var(--c-muted); margin:0;
  }
  audio#player { display:none; }

  /* Narrow: the dock must not vanish below twelve sections of score.
     The player card floats to the top as a sticky bar — timeline,
     transport, and karaoke stay in reach — and the reference cards
     (now playing, lyric, shapes) follow the score. */
  @media (max-width:1020px) {
    .studio { display:flex; flex-direction:column; }
    aside, .dock { display:contents; }
    .dock > * { margin:10px 12px 0; }
    .playercard {
      order:-1; position:sticky; top:0; z-index:20; margin:0;
      border-radius:0 0 14px 14px; border-top:0;
      border-left:0; border-right:0;
      box-shadow:0 10px 30px -18px rgb(0 0 0 / .45);
    }
    section.panel .nowbar { left:-14px; }
    main { padding:6px 14px 40px; }
    .about { margin:12px 12px 24px; }
  }
</style>
</head>
<body>
<div id="studio-root" class="root">
<div class="studio">
<main>
<header class="shead">
<h1>@@TITLE@@</h1>
<span class="facts">@@FACTS@@</span>
<button id="themebtn" class="themebtn" type="button">◐ dark</button>
</header>
<div class="controls">@@CONTROLS@@</div>
@@STRUCTURE_NOTE@@
@@MISSING@@
@@PANELS@@
<section class="questions"><h3>To finish this</h3>@@QUESTIONS@@</section>
@@SKIPPED@@
</main>
<aside>
<div class="dock">
<div class="card playercard">
<div id="studio-timeline"><song-timeline></song-timeline></div>
@@AUDIO@@
@@AUDIO_NOTE@@
<div class="transport">
<button id="playbtn" type="button" title="space">▶</button>
<div id="clocknow">0:00</div>
<button id="ratebtn" type="button">1× · keys ▾</button>
</div>
<div id="ratemenu" hidden>
<div class="dhead">Speed — same pitch, slower song</div>
<div class="ratepills">
<button type="button" class="ratepill" data-rate="0.5">0.5×</button>
<button type="button" class="ratepill" data-rate="0.65">0.65×</button>
<button type="button" class="ratepill" data-rate="0.75">0.75×</button>
<button type="button" class="ratepill" data-rate="0.85">0.85×</button>
<button type="button" class="ratepill on" data-rate="1">1×</button>
</div>
<div class="keysgrid">
<kbd>space</kbd><span>play / pause</span>
<span><kbd>←</kbd> <kbd>→</kbd></span><span>scrub 1 s</span>
<span><kbd>[</kbd> <kbd>]</kbd></span><span>slower / faster (pitch stays
put)</span>
<kbd>⌘-click</kbd><span>two spots = loop, <kbd>esc</kbd> clears</span>
<kbd>⌥</kbd><span>click/drag a chart to hear the notes</span>
</div>
</div>
<div id="karaoke"></div>
</div>
@@NOW_CARD@@
<div class="card">@@LYRIC_BLOCK@@</div>
@@SHAPES@@
@@STEMS@@
<p class="about">Analyzed on your machine by <code>music-stack</code>:
ffmpeg · Demucs · allin1 · Whisper · basic-pitch. One self-contained
file — mail it to anyone.</p>
</div>
</aside>
</div>
</div>
<script>window.SONG = @@PAYLOAD@@;</script>
<script>
@@REPORT_LIB@@
</script>
<script>
@@SCORE_PANEL@@
</script>
<script>
@@APP_JS@@
</script>
</body>
</html>
"""
