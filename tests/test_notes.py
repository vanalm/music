"""Note analysis tests -- pitch naming, guitar mapping, scale matching.

All pure computation over basic-pitch's note-event CSV, so unlike the tool
wrappers this is fully verifiable without any model installed.
"""

import os
import tempfile
import unittest
from pathlib import Path

from music_stack import notes


def csv_at(tmp, rows, header="start_time_s,end_time_s,pitch_midi,velocity"):
    path = os.path.join(tmp, "events.csv")
    lines = [header] + rows
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class NoteNameTests(unittest.TestCase):
    def test_middle_c(self):
        self.assertEqual(notes.note_name(60), "C4")

    def test_sharps_and_flats(self):
        self.assertEqual(notes.note_name(63), "D#4")
        self.assertEqual(notes.note_name(63, flats=True), "Eb4")

    def test_open_strings_name_correctly(self):
        # A sanity check on the tuning table itself.
        self.assertEqual(notes.note_name(notes.STANDARD_TUNING[6]), "E2")
        self.assertEqual(notes.note_name(notes.STANDARD_TUNING[3]), "G3")
        self.assertEqual(notes.note_name(notes.STANDARD_TUNING[2]), "B3")
        self.assertEqual(notes.note_name(notes.STANDARD_TUNING[1]), "E4")


class CsvReadingTests(unittest.TestCase):
    def test_reads_and_sorts_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = csv_at(tmp, ["1.0,1.4,67,80", "0.5,0.9,70,90"])
            events = notes.read_note_events(path)
        self.assertEqual([e["midi"] for e in events], [70, 67])
        self.assertEqual(events[0]["start"], 0.5)

    def test_matches_columns_by_name_not_position(self):
        """A reordered CSV must not silently shift pitch into velocity."""
        with tempfile.TemporaryDirectory() as tmp:
            path = csv_at(
                tmp,
                ["80,67,1.4,1.0"],
                header="velocity,pitch_midi,end_time_s,start_time_s",
            )
            events = notes.read_note_events(path)
        self.assertEqual(events[0]["midi"], 67)
        self.assertEqual(events[0]["start"], 1.0)

    def test_rejects_unrecognised_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = csv_at(tmp, ["1,2"], header="foo,bar")
            with self.assertRaises(ValueError):
                notes.read_note_events(path)

    def test_skips_unparseable_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = csv_at(tmp, ["0.1,0.2,64,80", "bad,rows,here,x"])
            self.assertEqual(len(notes.read_note_events(path)), 1)

    def test_rounds_fractional_midi(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = csv_at(tmp, ["0.1,0.2,63.8,80"])
            self.assertEqual(notes.read_note_events(path)[0]["midi"], 64)


class FilterTests(unittest.TestCase):
    EVENTS = [
        {"start": 0.0, "end": 0.02, "midi": 40, "velocity": 10},   # short + low
        {"start": 0.5, "end": 0.9, "midi": 67, "velocity": 90},
        {"start": 1.0, "end": 1.4, "midi": 65, "velocity": 88},
    ]

    def test_min_duration_drops_transient_noise(self):
        kept = notes.filter_events(self.EVENTS, min_duration=0.05)
        self.assertEqual([e["midi"] for e in kept], [67, 65])

    def test_pitch_window(self):
        kept = notes.filter_events(self.EVENTS, min_midi=66)
        self.assertEqual([e["midi"] for e in kept], [67])

    def test_time_window(self):
        kept = notes.filter_events(self.EVENTS, start=0.95)
        self.assertEqual([e["midi"] for e in kept], [65])


class GuitarPositionTests(unittest.TestCase):
    def test_open_high_e(self):
        positions = notes.guitar_positions(64)
        self.assertIn({"string": 1, "fret": 0}, positions)

    def test_same_note_on_multiple_strings(self):
        # G4 (67) is fret 3 on string 1, fret 8 on string 2, fret 12 on string 3.
        positions = notes.guitar_positions(67)
        self.assertEqual(
            positions,
            [{"string": 1, "fret": 3}, {"string": 2, "fret": 8},
             {"string": 3, "fret": 12}],
        )

    def test_note_below_the_top_three_strings_has_no_position(self):
        self.assertEqual(notes.guitar_positions(45), [])   # A2, needs string 5

    def test_all_six_strings_finds_it(self):
        positions = notes.guitar_positions(45, strings=tuple(range(1, 7)))
        self.assertIn({"string": 5, "fret": 0}, positions)


class FingeringTests(unittest.TestCase):
    def test_keeps_the_hand_in_one_position(self):
        """A descending line should not jump the hand up the neck."""
        events = [{"start": i * 0.2, "end": i * 0.2 + 0.1, "midi": m}
                  for i, m in enumerate([67, 65, 64, 62])]
        chosen = notes.choose_positions(events)
        frets = [c["fret"] for c in chosen]
        self.assertLessEqual(max(frets) - min(frets), 4)

    def test_notes_outside_the_strings_are_marked(self):
        chosen = notes.choose_positions([{"start": 0, "end": 1, "midi": 45}])
        self.assertIsNone(chosen[0]["string"])


class TabTests(unittest.TestCase):
    def test_renders_three_string_labels(self):
        events = [{"start": 0, "end": 0.1, "midi": 67},
                  {"start": 0.2, "end": 0.3, "midi": 65}]
        tab = notes.render_tab(notes.choose_positions(events))
        lines = tab.splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("e|"))
        self.assertTrue(lines[1].startswith("B|"))
        self.assertTrue(lines[2].startswith("G|"))


class ScaleMatchingTests(unittest.TestCase):
    def _events(self, midis):
        return [{"start": i * 0.2, "end": i * 0.2 + 0.1, "midi": m}
                for i, m in enumerate(midis)]

    def test_identifies_a_minor_pentatonic(self):
        # A C D E G, the A minor pentatonic, starting at A3 (57).
        best = notes.match_scales(self._events([57, 60, 62, 64, 67]))[0]
        self.assertEqual(best["root"], "A")
        self.assertIn("pentatonic", best["scale"])
        self.assertEqual(best["coverage"], 1.0)

    def test_blue_note_pulls_it_to_the_blues_scale(self):
        # Add Eb (63) -- the b5 -- and the blues scale should explain it all.
        events = self._events([57, 60, 62, 63, 64, 67])
        top = notes.match_scales(events)
        self.assertTrue(
            any(m["root"] == "A" and "blues" in m["scale"] and m["coverage"] == 1.0
                for m in top),
            [(m["root"], m["scale"], m["coverage"]) for m in top],
        )

    def test_prefers_the_tighter_scale_on_a_tie(self):
        """A 5-note scale that explains everything beats a 7-note one."""
        best = notes.match_scales(self._events([57, 60, 62, 64, 67]))[0]
        self.assertLessEqual(best["size"], 5)

    def test_empty_input(self):
        self.assertEqual(notes.match_scales([]), [])


class ContourTests(unittest.TestCase):
    def _events(self, midis):
        return [{"start": i * 0.2, "end": i * 0.2 + 0.1, "midi": m}
                for i, m in enumerate(midis)]

    def test_walking_down_is_descending(self):
        shape = notes.contour(self._events([67, 65, 64, 62, 60]))
        self.assertEqual(shape["direction"], "descending")
        self.assertEqual(shape["range_semitones"], 7)

    def test_ascending(self):
        self.assertEqual(
            notes.contour(self._events([60, 62, 64]))["direction"], "ascending"
        )

    def test_mixed(self):
        self.assertEqual(
            notes.contour(self._events([60, 64, 60, 64]))["direction"], "mixed"
        )

    def test_single_note(self):
        self.assertEqual(
            notes.contour(self._events([60]))["direction"], "single note"
        )


class ReportTests(unittest.TestCase):
    def test_full_report_covers_the_question_asked(self):
        # A descending bluesy line on the high strings.
        events = [{"start": i * 0.25, "end": i * 0.25 + 0.2, "midi": m}
                  for i, m in enumerate([67, 65, 64, 63, 62, 60])]
        described = notes.describe(events)
        report = notes.format_report(described)

        self.assertIn("Notes (6)", report)
        self.assertIn("descending", report)
        self.assertIn("Tab (high three strings", report)
        self.assertIn("Most likely scale", report)
        self.assertIn("string", report)
        # Flats by default -- idiomatic for blues.
        self.assertIn("Eb4", described["sequence"])

    def test_sharps_option(self):
        events = [{"start": 0, "end": 0.2, "midi": 63}]
        self.assertIn("D#4", notes.describe(events, flats=False)["sequence"])


if __name__ == "__main__":
    unittest.main()


class RelativeMajorAmbiguityTests(unittest.TestCase):
    """A pentatonic and its relative major share every note.

    The ranking must not pretend otherwise: the tonic decides the winner, but
    the alternative has to remain visible in the list.
    """

    def _events(self, midis):
        return [{"start": i * 0.2, "end": i * 0.2 + 0.1, "midi": m}
                for i, m in enumerate(midis)]

    def test_both_readings_are_offered(self):
        ranked = notes.match_scales(self._events([57, 60, 62, 64, 67]))
        pairs = [(m["root"], m["scale"]) for m in ranked]
        self.assertEqual(pairs[0], ("A", "minor pentatonic"))
        self.assertIn(("C", "major pentatonic"), pairs)

    def test_fit_penalises_a_scale_with_unplayed_degrees(self):
        # The major scale contains the pentatonic, so coverage ties -- only
        # the fit term separates them.
        ranked = notes.match_scales(self._events([57, 60, 62, 64, 67]))
        best = ranked[0]
        self.assertEqual(best["fit"], 1.0)
        self.assertEqual(best["unused"], 0)

    def test_resolution_note_drives_the_tonic(self):
        # Same pitch classes, but resolving to C instead of starting on A.
        ranked = notes.match_scales(self._events([64, 67, 57, 62, 60]))
        self.assertEqual(ranked[0]["root"], "C")

    def test_modes_of_one_scale_all_survive_to_the_list(self):
        ranked = notes.match_scales(
            self._events([60, 62, 64, 65, 67, 69, 71, 72]), top=6
        )
        self.assertEqual(ranked[0]["root"], "C")
        self.assertEqual(ranked[0]["scale"], "major")
