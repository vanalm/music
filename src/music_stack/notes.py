"""Note-level analysis: pitches, guitar positions, and what scale a lick is in.

Structure and stems tell you how a song is arranged. They do not tell you
*what you played*. That needs pitch transcription — Spotify's `basic-pitch`,
which is polyphonic, instrument-agnostic, and writes a note-event CSV this
module reads.

Everything here is pure computation over that CSV: no model, no network. It
turns "a cool bluesy thing walking down the high strings" into named notes,
fret positions, and a scale hypothesis.
"""

import csv
from pathlib import Path

SHARP = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
FLAT = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")

#: Standard tuning, open-string MIDI numbers, string 1 = high E.
STANDARD_TUNING = {1: 64, 2: 59, 3: 55, 4: 50, 5: 45, 6: 40}

#: "The highest three strings" — G, B, high E.
TOP_THREE = (1, 2, 3)

MAX_FRET = 22

#: Interval sets, as semitones from the root.
SCALES = {
    "minor pentatonic": (0, 3, 5, 7, 10),
    "blues (minor)": (0, 3, 5, 6, 7, 10),
    "major pentatonic": (0, 2, 4, 7, 9),
    "blues (major)": (0, 2, 3, 4, 7, 9),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "natural minor": (0, 2, 3, 5, 7, 8, 10),
    "major": (0, 2, 4, 5, 7, 9, 11),
}


def note_name(midi, *, flats=False):
    """MIDI number to scientific pitch notation, e.g. 63 -> 'D#4' or 'Eb4'."""
    names = FLAT if flats else SHARP
    return "{}{}".format(names[int(midi) % 12], int(midi) // 12 - 1)


def pitch_class(midi):
    return int(midi) % 12


def read_note_events(path):
    """Parse basic-pitch's note-event CSV into sorted note dicts.

    Columns are matched by header name rather than position, so a future
    column reorder or addition does not silently shift the data.
    """
    rows = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = {(f or "").strip().lower(): f for f in (reader.fieldnames or [])}

        def pick(*candidates):
            for c in candidates:
                if c in fields:
                    return fields[c]
            return None

        start_f = pick("start_time_s", "start_time", "start")
        end_f = pick("end_time_s", "end_time", "end")
        pitch_f = pick("pitch_midi", "pitch", "midi_note", "note")
        vel_f = pick("velocity", "amplitude")
        if not (start_f and pitch_f):
            raise ValueError(
                "Unrecognised note-event CSV; columns were {}".format(
                    reader.fieldnames
                )
            )

        for row in reader:
            try:
                midi = int(round(float(row[pitch_f])))
                start = float(row[start_f])
            except (TypeError, ValueError):
                continue
            end = start
            if end_f:
                try:
                    end = float(row[end_f])
                except (TypeError, ValueError):
                    pass
            velocity = None
            if vel_f:
                try:
                    velocity = float(row[vel_f])
                except (TypeError, ValueError):
                    velocity = None
            rows.append(
                {
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "midi": midi,
                    "velocity": velocity,
                }
            )
    rows.sort(key=lambda r: (r["start"], r["midi"]))
    return rows


def filter_events(events, *, start=None, end=None, min_midi=None, max_midi=None,
                  min_duration=0.0):
    """Narrow the transcription to the part you care about.

    ``min_duration`` drops the very short spurious notes that polyphonic
    transcription produces around string noise and transients.
    """
    out = []
    for e in events:
        if start is not None and e["end"] < start:
            continue
        if end is not None and e["start"] > end:
            continue
        if min_midi is not None and e["midi"] < min_midi:
            continue
        if max_midi is not None and e["midi"] > max_midi:
            continue
        if (e["end"] - e["start"]) < min_duration:
            continue
        out.append(e)
    return out


def guitar_positions(midi, strings=TOP_THREE, tuning=None, max_fret=MAX_FRET):
    """Every way to play *midi* on the given strings. Lowest fret first."""
    tuning = tuning or STANDARD_TUNING
    out = []
    for s in strings:
        open_midi = tuning.get(s)
        if open_midi is None:
            continue
        fret = int(midi) - open_midi
        if 0 <= fret <= max_fret:
            out.append({"string": s, "fret": fret})
    return sorted(out, key=lambda p: p["fret"])


def choose_positions(events, strings=TOP_THREE, tuning=None, prefer_fret=None):
    """Pick one playable position per note, keeping the hand in one place.

    A greedy pass over a sticky four-fret hand window. ``prefer_fret``
    seeds where the window sits; notes inside the window (index finger one
    fret back, pinky four ahead) are free, and the window shifts only when
    a note is unreachable — and then minimally, the way a hand actually
    moves. Open strings are reachable from *any* position, so they never
    drag the window: an anchor that simply followed the previous note's
    fret collapsed to the nut at the first open string, and a "5th
    position" tab stayed there only for its opening notes. Different
    seeds give the same notes in different neck positions — none of them
    is "the" fingering, because the audio cannot say which string was
    played.
    """
    chosen = []
    anchor = prefer_fret
    for e in events:
        options = guitar_positions(e["midi"], strings=strings, tuning=tuning)
        if not options:
            chosen.append({**e, "string": None, "fret": None})
            continue
        if anchor is None:
            pick = options[0]
            if pick["fret"]:
                anchor = pick["fret"]
        else:
            lo, hi = anchor - 1, anchor + 4

            def reach(p):
                fret = p["fret"]
                if fret == 0 or lo <= fret <= hi:
                    away = 0
                else:
                    away = lo - fret if fret < lo else fret - hi
                return (away, abs(fret - anchor), fret)

            pick = min(options, key=reach)
            fret = pick["fret"]
            if fret and not (lo <= fret <= hi):
                anchor = fret - 4 if fret > hi else fret + 1
        chosen.append({**e, "string": pick["string"], "fret": pick["fret"]})
    return chosen


def render_tab(positioned, strings=TOP_THREE, width=4):
    """Render chosen positions as ASCII tab, one column per note."""
    labels = {1: "e", 2: "B", 3: "G", 4: "D", 5: "A", 6: "E"}
    ordered = sorted(strings)
    lines = {s: "{}|".format(labels.get(s, "?")) for s in ordered}
    for note in positioned:
        for s in ordered:
            cell = "-" * width
            if note.get("string") == s and note.get("fret") is not None:
                text = str(note["fret"])
                cell = "-" + text + "-" * (width - 1 - len(text))
            lines[s] += cell + "-"
    return "\n".join(lines[s] + "|" for s in ordered)


def match_scales(events, *, top=4):
    """Rank scales by how well they explain the notes actually played.

    Coverage alone cannot settle the answer: a minor pentatonic and its
    relative major contain *identical* notes (A C D E G is both A minor
    pentatonic and C major pentatonic). Only the tonic separates them, so the
    ranking adds a tonic bonus from where the line rests — the last note
    weighs most, since phrases resolve; then the first note; then how often
    the candidate root is played at all.

    The result is a ranked list rather than a single answer, because for some
    note sets the ambiguity is real and worth seeing.
    """
    if not events:
        return []
    weights = {}
    for e in events:
        weights[pitch_class(e["midi"])] = weights.get(pitch_class(e["midi"]), 0) + 1
    total = sum(weights.values())
    first_pc = pitch_class(events[0]["midi"])
    last_pc = pitch_class(events[-1]["midi"])

    scored = []
    for root in range(12):
        tonic = 0.0
        if root == last_pc:
            tonic += 2.0
        if root == first_pc:
            tonic += 1.0
        tonic += weights.get(root, 0) / total

        for name, intervals in SCALES.items():
            members = {(root + i) % 12 for i in intervals}
            played = set(weights)
            explained = sum(w for pc, w in weights.items() if pc in members)
            coverage = explained / total
            # Coverage alone rewards big scales: a 7-note scale contains a
            # 5-note one, so it can never explain less. Jaccard also penalises
            # the scale degrees that were never played, which is what makes a
            # pentatonic beat the major scale that contains it.
            fit = len(played & members) / len(played | members)
            scored.append(
                {
                    "root": SHARP[root],
                    "root_flat": FLAT[root],
                    "scale": name,
                    "coverage": round(coverage, 3),
                    "fit": round(fit, 3),
                    "tonic_evidence": round(tonic, 3),
                    "size": len(intervals),
                    "unused": len(members - played),
                }
            )
    # Explain what was played, fit it tightly, then let the tonic break ties
    # between scales that share a note set (relative major/minor).
    scored.sort(
        key=lambda s: (-s["coverage"], -s["fit"], -s["tonic_evidence"], s["size"])
    )
    return scored[:top]


def contour(events):
    """Describe the shape of the line — the 'walking down' question."""
    pitches = [e["midi"] for e in events]
    if len(pitches) < 2:
        return {"direction": "single note", "steps": [], "range_semitones": 0}
    steps = [b - a for a, b in zip(pitches, pitches[1:])]
    down = sum(1 for s in steps if s < 0)
    up = sum(1 for s in steps if s > 0)
    if down and not up:
        direction = "descending"
    elif up and not down:
        direction = "ascending"
    elif down > up * 2:
        direction = "mostly descending"
    elif up > down * 2:
        direction = "mostly ascending"
    else:
        direction = "mixed"
    return {
        "direction": direction,
        "steps": steps,
        "range_semitones": max(pitches) - min(pitches),
    }


def describe(events, *, strings=TOP_THREE, flats=True, tuning=None):
    """Full report on a lick: notes, tab, scale candidates, and shape."""
    positioned = choose_positions(events, strings=strings, tuning=tuning)
    scales = match_scales(events)
    shape = contour(events)
    return {
        "note_count": len(events),
        "notes": [
            {
                "time": e["start"],
                "name": note_name(e["midi"], flats=flats),
                "midi": e["midi"],
                "string": e.get("string"),
                "fret": e.get("fret"),
            }
            for e in positioned
        ],
        "sequence": " ".join(note_name(e["midi"], flats=flats) for e in events),
        "tab": render_tab(positioned, strings=strings),
        "scales": scales,
        "contour": shape,
    }


def format_report(described, *, flats=True):
    """Human-readable rendering of :func:`describe`."""
    lines = []
    lines.append("Notes ({}): {}".format(described["note_count"], described["sequence"]))
    shape = described["contour"]
    lines.append(
        "Shape: {} over {} semitones".format(
            shape["direction"], shape["range_semitones"]
        )
    )
    lines.append("")
    lines.append("Tab (high three strings, standard tuning):")
    lines.append(described["tab"])
    lines.append("")
    if described["scales"]:
        lines.append("Most likely scale:")
        for s in described["scales"]:
            root = s["root_flat"] if flats else s["root"]
            lines.append(
                "  {:<3} {:<18} explains {:.0%} of the notes".format(
                    root, s["scale"], s["coverage"]
                )
            )
    lines.append("")
    lines.append("Note-by-note:")
    for n in described["notes"]:
        position = (
            "string {} fret {}".format(n["string"], n["fret"])
            if n["string"]
            else "outside the chosen strings"
        )
        lines.append("  {:>6.2f}s  {:<4} {}".format(n["time"], n["name"], position))
    return "\n".join(lines)
