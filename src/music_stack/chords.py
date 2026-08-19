"""Polyphony: grouping simultaneous notes, naming chords, and fingering them.

`basic-pitch` is polyphonic — it already reports overlapping notes. What it
does not do is say "that was an Am7". This module supplies the musical layer:

1. :func:`group_simultaneities` clusters note events that start together.
2. :func:`name_chord` identifies the chord from its pitch classes and bass.
3. :func:`voice_chord` finds where those exact notes sit on the fretboard.

Point 3 is deliberately *descriptive*, not prescriptive. It fingers the notes
you actually played rather than substituting a textbook shape, because the
question being answered is "what did I do there", not "how is this chord
normally voiced".
"""

import re
from itertools import combinations, permutations

from .notes import FLAT, SHARP, STANDARD_TUNING, note_name, pitch_class

MAX_FRET = 22

#: A comfortable hand span. Fretted notes outside this are treated as a
#: separate position rather than one grip.
MAX_SPAN = 5

#: Chord qualities as semitones from the root, ordered so that when two
#: readings fit equally the simpler, more common one is found first.
QUALITIES = (
    ("5", (0, 7)),
    ("", (0, 4, 7)),
    ("m", (0, 3, 7)),
    ("sus2", (0, 2, 7)),
    ("sus4", (0, 5, 7)),
    ("dim", (0, 3, 6)),
    ("aug", (0, 4, 8)),
    ("6", (0, 4, 7, 9)),
    ("m6", (0, 3, 7, 9)),
    ("7", (0, 4, 7, 10)),
    ("maj7", (0, 4, 7, 11)),
    ("m7", (0, 3, 7, 10)),
    ("mMaj7", (0, 3, 7, 11)),
    ("m7b5", (0, 3, 6, 10)),
    ("dim7", (0, 3, 6, 9)),
    ("7sus4", (0, 5, 7, 10)),
    ("add9", (0, 2, 4, 7)),
    ("madd9", (0, 2, 3, 7)),
    ("9", (0, 2, 4, 7, 10)),
    ("m9", (0, 2, 3, 7, 10)),
    ("maj9", (0, 2, 4, 7, 11)),
    ("69", (0, 2, 4, 7, 9)),
    ("11", (0, 2, 4, 5, 7, 10)),
    ("13", (0, 2, 4, 7, 9, 10)),
)


def group_simultaneities(events, *, window=0.08, max_width=None, min_notes=1):
    """Cluster note events struck together.

    A strummed chord is not simultaneous — the pick crosses the strings over
    perhaps 20 ms per string, so a six-string strum can be 100 ms wide end to
    end even though no two adjacent notes are far apart. Measuring every note
    against the *group's* first onset therefore splits the last string off a
    wide strum, while measuring against the *previous* note alone would let a
    fast run chain into one enormous chord.

    So both apply: a note joins if it is within *window* of the previous note
    **and** within *max_width* of where the group began. *max_width* defaults
    to 2.5x *window*, so widening one widens the other — setting a generous
    window and then being silently capped would be a trap.
    """
    if max_width is None:
        max_width = window * 2.5
    ordered = sorted(events, key=lambda e: e["start"])
    groups = []
    for event in ordered:
        if (
            groups
            and event["start"] - groups[-1]["last"] <= window
            and event["start"] - groups[-1]["start"] <= max_width
        ):
            groups[-1]["events"].append(event)
            groups[-1]["end"] = max(groups[-1]["end"], event["end"])
            groups[-1]["last"] = event["start"]
        else:
            groups.append(
                {
                    "start": event["start"],
                    "last": event["start"],
                    "end": event["end"],
                    "events": [event],
                }
            )
    for group in groups:
        group["midis"] = sorted(e["midi"] for e in group["events"])
        group["bass"] = group["midis"][0]
        group["note_count"] = len(group["midis"])
    return [g for g in groups if g["note_count"] >= min_notes]


def name_chord(midis, *, flats=True):
    """Identify the chord formed by *midis*.

    Returns the symbol, the quality, the bass note, and how exactly the notes
    matched. ``exact`` distinguishes "these notes are precisely an Am7" from
    "an Am7 with something extra sounding", which matters when transcription
    has thrown in a spurious partial.
    """
    midis = sorted(set(int(m) for m in midis))
    if not midis:
        return None
    names = FLAT if flats else SHARP
    classes = {pitch_class(m) for m in midis}
    bass_pc = pitch_class(midis[0])

    if len(classes) == 1:
        return {
            "symbol": names[bass_pc],
            "root": names[bass_pc],
            "quality": "unison",
            "bass": note_name(midis[0], flats=flats),
            "exact": True,
            "extra": [],
            "missing": [],
            "notes": [note_name(m, flats=flats) for m in midis],
        }

    best = None
    for root in range(12):
        for quality, intervals in QUALITIES:
            members = {(root + i) % 12 for i in intervals}
            if not members:
                continue
            extra = classes - members
            missing = members - classes
            # Rank: fewest foreign notes, then fewest absent chord tones, then
            # roots that match the bass, then the smaller quality.
            #
            # The bass term is doing real work. A C E G is *exactly* Am7 and
            # *exactly* C6 -- the note set cannot separate them, only what is
            # underneath can. With A in the bass a player calls it Am7; with C
            # in the bass, C6. Without this term the tie broke on table order,
            # which is musically arbitrary.
            score = (
                len(extra),
                len(missing),
                0 if root == bass_pc else 1,
                len(intervals),
            )
            if best is None or score < best[0]:
                best = (score, root, quality, extra, missing)

    _score, root, quality, extra, missing = best
    symbol = "{}{}".format(names[root], quality)
    if bass_pc != root:
        symbol += "/{}".format(names[bass_pc])
    return {
        "symbol": symbol,
        "root": names[root],
        "quality": quality or "major",
        "bass": note_name(midis[0], flats=flats),
        "inversion": bass_pc != root,
        "exact": not extra and not missing,
        "extra": sorted(names[pc] for pc in extra),
        "missing": sorted(names[pc] for pc in missing),
        "notes": [note_name(m, flats=flats) for m in midis],
    }


def fret_positions(midi, *, tuning=None, max_fret=MAX_FRET):
    """Every (string, fret) that sounds *midi*, across all six strings."""
    tuning = tuning or STANDARD_TUNING
    out = []
    for string, open_midi in tuning.items():
        fret = int(midi) - open_midi
        if 0 <= fret <= max_fret:
            out.append((string, fret))
    return out


def voice_chord(midis, *, tuning=None, max_span=MAX_SPAN, max_fret=MAX_FRET):
    """Find the most playable way to finger exactly these notes.

    One note per string, ranked by hand span, then position on the neck, then
    how many open strings it uses. Returns ``None`` if no assignment exists —
    which is a real answer: six detected pitches spanning three octaves cannot
    be one guitar grip, and saying so beats inventing a shape.
    """
    tuning = tuning or STANDARD_TUNING
    midis = sorted(set(int(m) for m in midis))
    if not midis or len(midis) > len(tuning):
        return None

    options = [fret_positions(m, tuning=tuning, max_fret=max_fret) for m in midis]
    if any(not o for o in options):
        return None

    best = None
    # At most 6 notes over 6 strings; the search space stays trivial.
    for assignment in _assignments(options):
        strings = [s for s, _f in assignment]
        if len(set(strings)) != len(strings):
            continue
        fretted = [f for _s, f in assignment if f > 0]
        span = (max(fretted) - min(fretted)) if fretted else 0
        if span > max_span:
            continue
        # A voicing where a lower-pitched note sits on a higher string is
        # physically possible but not what a player does; penalise crossings.
        crossings = sum(
            1
            for (s1, _f1), (s2, _f2) in zip(assignment, assignment[1:])
            if s2 >= s1
        )
        opens = sum(1 for _s, f in assignment if f == 0)
        low = min(fretted) if fretted else 0
        score = (crossings, span, low, -opens)
        if best is None or score < best[0]:
            best = (score, assignment)

    if best is None:
        return None

    _score, assignment = best
    positions = [
        {"string": s, "fret": f, "midi": m, "name": note_name(m)}
        for (s, f), m in zip(assignment, midis)
    ]
    positions.sort(key=lambda p: -p["string"])
    fretted = [p["fret"] for p in positions if p["fret"] > 0]
    return {
        "positions": positions,
        "span": (max(fretted) - min(fretted)) if fretted else 0,
        "lowest_fret": min(fretted) if fretted else 0,
        "open_strings": sum(1 for p in positions if p["fret"] == 0),
        "shorthand": shorthand(positions),
    }


def _assignments(options):
    """Yield one (string, fret) choice per note, without repeating a string."""
    if not options:
        yield []
        return
    head, tail = options[0], options[1:]
    for choice in head:
        for rest in _assignments(tail):
            if any(choice[0] == s for s, _f in rest):
                continue
            yield [choice] + rest


def shorthand(positions):
    """Render a voicing as the usual six-character form, e.g. ``x32010``."""
    by_string = {p["string"]: p["fret"] for p in positions}
    out = []
    for string in range(6, 0, -1):
        fret = by_string.get(string)
        if fret is None:
            out.append("x")
        elif fret < 10:
            out.append(str(fret))
        else:
            out.append("({})".format(fret))
    return "".join(out)


#: Open-position grips a guitarist actually reaches for, by exact symbol
#: (slash bass stripped). Everything else goes through the movable forms.
OPEN_SHAPES = {
    "C": "x32010", "A": "x02220", "G": "320003", "E": "022100",
    "D": "xx0232", "F": "133211",
    "Am": "x02210", "Em": "022000", "Dm": "xx0231",
    "A7": "x02020", "B7": "x21202", "C7": "x32310", "D7": "xx0212",
    "E7": "020100", "G7": "320001",
    "Am7": "x02010", "Em7": "022030", "Dm7": "xx0211",
    "Cmaj7": "x32000", "Amaj7": "x02120", "Dmaj7": "xx0222",
    "Emaj7": "021100", "Fmaj7": "xx3210", "Gmaj7": "320002",
    "Asus2": "x02200", "Asus4": "x02230", "Dsus2": "xx0230",
    "Dsus4": "xx0233", "Esus4": "022200",
    "E5": "022xxx", "A5": "x022xx", "D5": "xx023x",
}

#: Movable barre forms: quality -> [(root string, frets low-E..high-e
#: relative to the barre, None = muted)]. E-form first, A-form second.
MOVABLE_SHAPES = {
    "": [(6, (0, 2, 2, 1, 0, 0)), (5, (None, 0, 2, 2, 2, 0))],
    "m": [(6, (0, 2, 2, 0, 0, 0)), (5, (None, 0, 2, 2, 1, 0))],
    "7": [(6, (0, 2, 0, 1, 0, 0)), (5, (None, 0, 2, 0, 2, 0))],
    "m7": [(6, (0, 2, 0, 0, 0, 0)), (5, (None, 0, 2, 0, 1, 0))],
    "sus4": [(6, (0, 2, 2, 2, 0, 0)), (5, (None, 0, 2, 2, 3, 0))],
    "5": [(6, (0, 2, 2, None, None, None)),
          (5, (None, 0, 2, 2, None, None))],
}

_PC = {name: pc for pc, name in enumerate(SHARP)}
_PC.update({name: pc for pc, name in enumerate(FLAT)})

_SYMBOL_RE = re.compile(r"^([A-G][#b]?)(.*)$")


def _positions_from_shorthand(short):
    return [
        {"string": 6 - i, "fret": int(ch)}
        for i, ch in enumerate(short)
        if ch != "x"
    ]


def textbook_shape(symbol):
    """The standard grip for *symbol*, or ``None`` when there isn't one.

    The detected voicings are honest about the notes but not about the
    hand — transcription noise fingered literally looks like nothing a
    player would grab. For song-level charts, a common chord should show
    the grip everyone plays; only oddities fall back to the detected one.
    Slash basses use the plain grip of the main chord.
    """
    core = (symbol or "").split("/")[0]
    if core in OPEN_SHAPES:
        return _positions_from_shorthand(OPEN_SHAPES[core])
    match = _SYMBOL_RE.match(core)
    if not match:
        return None
    root, quality = match.groups()
    forms = MOVABLE_SHAPES.get(quality)
    root_pc = _PC.get(root)
    if not forms or root_pc is None:
        return None
    best = None
    for root_string, rel in forms:
        barre = (root_pc - pitch_class(STANDARD_TUNING[root_string])) % 12
        if barre == 0:
            barre = 12  # the open version would already be in OPEN_SHAPES
        if best is None or barre < best[0]:
            best = (barre, rel)
    barre, rel = best
    return [
        {"string": 6 - i, "fret": barre + f}
        for i, f in enumerate(rel)
        if f is not None
    ]


def render_diagram(voicing, *, name=None, width=5):
    """Draw a chord box: strings as rows, frets as columns."""
    if not voicing:
        return "(no single-position fingering for these notes)"
    positions = {p["string"]: p["fret"] for p in voicing["positions"]}
    fretted = [f for f in positions.values() if f > 0]
    start = max(1, min(fretted)) if fretted else 1
    if start > 1 and max(fretted) - start < width:
        pass
    else:
        start = 1

    labels = {6: "E", 5: "A", 4: "D", 3: "G", 2: "B", 1: "e"}
    lines = []
    if name:
        lines.append("  {}   {}".format(name, voicing["shorthand"]))
    else:
        lines.append("  {}".format(voicing["shorthand"]))
    for string in range(6, 0, -1):
        fret = positions.get(string)
        marker = "x" if fret is None else ("o" if fret == 0 else " ")
        cells = []
        for offset in range(width):
            this_fret = start + offset
            cells.append("-@-" if fret == this_fret else "---")
        lines.append("{} {} |{}|".format(labels[string], marker, "|".join(cells)))
    footer = "     " + "  ".join(
        "{:<2}".format(start + i) for i in range(width)
    )
    lines.append(footer)
    return "\n".join(lines)


def render_chord_tab(chords, *, width=6):
    """Stacked tab across all six strings, one column per chord."""
    labels = {6: "E", 5: "A", 4: "D", 3: "G", 2: "B", 1: "e"}
    rows = {s: "{}|".format(labels[s]) for s in range(1, 7)}
    for chord in chords:
        voicing = chord.get("voicing")
        by_string = (
            {p["string"]: p["fret"] for p in voicing["positions"]} if voicing else {}
        )
        for string in range(1, 7):
            fret = by_string.get(string)
            cell = "-" * width if fret is None else "-{}{}".format(
                fret, "-" * (width - 1 - len(str(fret)))
            )
            rows[string] += cell + "-"
    return "\n".join(rows[s] + "|" for s in range(1, 7))


def analyze(events, *, window=0.08, max_width=None, min_notes=2, flats=True,
            tuning=None):
    """Group *events* into chords, name them, and finger them."""
    out = []
    for group in group_simultaneities(
        events, window=window, max_width=max_width, min_notes=min_notes
    ):
        chord = name_chord(group["midis"], flats=flats)
        out.append(
            {
                "start": group["start"],
                "end": group["end"],
                "midis": group["midis"],
                "chord": chord,
                "voicing": voice_chord(group["midis"], tuning=tuning),
            }
        )
    return out


def format_chords(analysed, *, show_diagrams=True):
    """Readable report: progression, tab, and one box per distinct shape."""
    if not analysed:
        return "No simultaneous notes found — this passage is single-line."

    lines = []
    progression = " ".join(
        (c["chord"]["symbol"] if c["chord"] else "?") for c in analysed
    )
    lines.append("Progression: {}".format(progression))
    lines.append("")
    lines.append("Tab:")
    lines.append(render_chord_tab(analysed))
    lines.append("")

    lines.append("Chord by chord:")
    for c in analysed:
        chord = c["chord"] or {}
        flags = []
        if not chord.get("exact"):
            if chord.get("extra"):
                flags.append("extra {}".format(", ".join(chord["extra"])))
            if chord.get("missing"):
                flags.append("missing {}".format(", ".join(chord["missing"])))
        note = "  ({})".format("; ".join(flags)) if flags else ""
        shape = c["voicing"]["shorthand"] if c["voicing"] else "no single position"
        lines.append(
            "  {:>6.2f}s  {:<9} {:<20} {}{}".format(
                c["start"],
                chord.get("symbol", "?"),
                " ".join(chord.get("notes", [])),
                shape,
                note,
            )
        )

    if show_diagrams:
        seen = {}
        for c in analysed:
            if not c["voicing"]:
                continue
            key = c["voicing"]["shorthand"]
            if key not in seen:
                seen[key] = (c["chord"]["symbol"] if c["chord"] else "?", c["voicing"])
        if seen:
            lines.append("")
            lines.append("Shapes:")
            for symbol, voicing in seen.values():
                lines.append("")
                lines.append(render_diagram(voicing, name=symbol))
    return "\n".join(lines)
