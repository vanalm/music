"""MusicXML export — the route from note events to actual sheet music.

MuseScore (free), Guitar Pro, Dorico, and Sibelius all open MusicXML, so this
is the format that turns a transcription into notation you can read, edit, and
print. It also carries more than MIDI does: chord symbols, a title, and an
explicit key and time signature.

**Quantisation is the honest limitation.** Note starts and lengths are snapped
to a sixteenth-note grid against a fixed tempo. That is right for most strummed
and picked material and wrong for anything rubato, swung, or in triplets — the
notation will look tidier and squarer than what you actually played. It is a
readable starting point for a human editor, not a forensic record. When the
rhythm matters more than the reading, open the MIDI instead: it keeps the raw
timing.
"""

from xml.sax.saxutils import escape

#: Divisions per quarter note. 4 gives a sixteenth-note grid.
DIVISIONS = 4

#: Ticks -> notated duration. Anything not listed is approximated downward.
NOTE_TYPES = (
    (16, "whole"),
    (8, "half"),
    (6, "half"),        # dotted quarter, written as half for legibility
    (4, "quarter"),
    (3, "quarter"),     # dotted eighth
    (2, "eighth"),
    (1, "16th"),
)

#: MIDI pitch class -> (step, alter). Sharps, which notate cleanly by default.
_PITCH = {
    0: ("C", 0), 1: ("C", 1), 2: ("D", 0), 3: ("D", 1), 4: ("E", 0),
    5: ("F", 0), 6: ("F", 1), 7: ("G", 0), 8: ("G", 1), 9: ("A", 0),
    10: ("A", 1), 11: ("B", 0),
}


def pitch_elements(midi):
    """Return the ``<pitch>`` body for a MIDI number."""
    step, alter = _PITCH[int(midi) % 12]
    octave = int(midi) // 12 - 1
    parts = ["<step>{}</step>".format(step)]
    if alter:
        parts.append("<alter>{}</alter>".format(alter))
    parts.append("<octave>{}</octave>".format(octave))
    return "".join(parts)


def note_type(ticks):
    """Nearest notated duration at or below *ticks*."""
    for size, name in NOTE_TYPES:
        if ticks >= size:
            return name
    return "16th"


def quantize(seconds, bpm, *, divisions=DIVISIONS):
    """Convert seconds to ticks on the grid, never returning less than one."""
    quarters = seconds * bpm / 60.0
    return max(1, int(round(quarters * divisions)))


def build(groups, *, bpm=120, title="Untitled", beats_per_measure=4,
          divisions=DIVISIONS, part_name="Guitar"):
    """Render grouped note events as a MusicXML score.

    *groups* is the output of :func:`music_stack.chords.group_simultaneities`,
    optionally with a ``chord`` key whose ``symbol`` becomes a chord symbol
    above the staff.
    """
    measure_ticks = beats_per_measure * divisions
    events = []
    for group in groups:
        start = quantize(group["start"], bpm, divisions=divisions) - 1
        length = quantize(
            max(group["end"] - group["start"], 60.0 / bpm / 8), bpm,
            divisions=divisions,
        )
        events.append(
            {
                "start": max(0, start),
                "ticks": length,
                "midis": sorted(group["midis"]),
                "symbol": (group.get("chord") or {}).get("symbol"),
            }
        )
    events.sort(key=lambda e: e["start"])

    body = []
    cursor = 0
    measure = 1
    measure_used = 0
    body.append(_measure_open(measure, divisions, bpm, beats_per_measure,
                              part_name, first=True))

    for event in events:
        gap = event["start"] - cursor
        while gap > 0:
            room = measure_ticks - measure_used
            rest = min(gap, room)
            body.append(_rest(rest, divisions))
            measure_used += rest
            cursor += rest
            gap -= rest
            if measure_used >= measure_ticks:
                body.append("</measure>")
                measure += 1
                measure_used = 0
                body.append(_measure_open(measure, divisions, bpm,
                                          beats_per_measure, part_name))

        remaining = event["ticks"]
        first_slice = True
        while remaining > 0:
            room = measure_ticks - measure_used
            if room <= 0:
                body.append("</measure>")
                measure += 1
                measure_used = 0
                room = measure_ticks
                body.append(_measure_open(measure, divisions, bpm,
                                          beats_per_measure, part_name))
            piece = min(remaining, room)
            if first_slice and event["symbol"]:
                body.append(_harmony(event["symbol"]))
            for index, midi in enumerate(event["midis"]):
                body.append(_note(midi, piece, chord=index > 0))
            measure_used += piece
            cursor += piece
            remaining -= piece
            first_slice = False

    tail = measure_ticks - measure_used
    if tail > 0:
        body.append(_rest(tail, divisions))
    body.append("</measure>")

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 '
        'Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">\n'
        '<score-partwise version="4.0">\n'
        "  <work><work-title>{title}</work-title></work>\n"
        "  <part-list>\n"
        '    <score-part id="P1"><part-name>{part}</part-name></score-part>\n'
        "  </part-list>\n"
        '  <part id="P1">\n{body}\n  </part>\n'
        "</score-partwise>\n"
    ).format(title=escape(title), part=escape(part_name), body="\n".join(body))


def _measure_open(number, divisions, bpm, beats, part_name, first=False):
    attributes = (
        "<attributes>"
        "<divisions>{d}</divisions>"
        "<key><fifths>0</fifths></key>"
        "<time><beats>{b}</beats><beat-type>4</beat-type></time>"
        "<clef><sign>G</sign><line>2</line></clef>"
        "</attributes>"
    ).format(d=divisions, b=beats)
    tempo = (
        '<direction placement="above"><direction-type><metronome>'
        "<beat-unit>quarter</beat-unit><per-minute>{bpm}</per-minute>"
        "</metronome></direction-type>"
        '<sound tempo="{bpm}"/></direction>'
    ).format(bpm=int(round(bpm)))
    inner = attributes + tempo if first else ""
    return '    <measure number="{}">{}'.format(number, inner)


def _harmony(symbol):
    """A chord symbol above the staff.

    MusicXML wants the root and kind separately, so the symbol is split back
    apart. Anything unrecognised falls back to 'other' with the text shown
    verbatim, which notation software renders as written.
    """
    root = symbol[0]
    alter = 0
    rest = symbol[1:]
    if rest[:1] in ("#", "b"):
        alter = 1 if rest[0] == "#" else -1
        rest = rest[1:]
    rest = rest.split("/")[0]
    kind = {
        "": "major", "m": "minor", "7": "dominant", "maj7": "major-seventh",
        "m7": "minor-seventh", "dim": "diminished", "dim7": "diminished-seventh",
        "aug": "augmented", "6": "major-sixth", "m6": "minor-sixth",
        "sus2": "suspended-second", "sus4": "suspended-fourth",
        "m7b5": "half-diminished", "9": "dominant-ninth",
        "maj9": "major-ninth", "m9": "minor-ninth", "5": "power",
    }.get(rest, "other")
    alter_xml = "<root-alter>{}</root-alter>".format(alter) if alter else ""
    return (
        '      <harmony><root><root-step>{root}</root-step>{alter}</root>'
        '<kind text="{text}">{kind}</kind></harmony>'
    ).format(root=root, alter=alter_xml, text=escape(symbol), kind=kind)


def _note(midi, ticks, *, chord=False):
    return (
        "      <note>{chord}<pitch>{pitch}</pitch>"
        "<duration>{dur}</duration><type>{type}</type></note>"
    ).format(
        chord="<chord/>" if chord else "",
        pitch=pitch_elements(midi),
        dur=ticks,
        type=note_type(ticks),
    )


def _rest(ticks, divisions):
    return (
        "      <note><rest/><duration>{dur}</duration><type>{type}</type></note>"
    ).format(dur=ticks, type=note_type(ticks))
