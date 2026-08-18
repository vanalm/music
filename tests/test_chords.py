"""Chord detection, naming, voicing, and MusicXML export.

All pure computation over note events, so unlike the model wrappers this is
genuinely verifiable here.
"""

import unittest
import xml.etree.ElementTree as ET

from music_stack import chords, musicxml


def stack(midis, start=0.0, spread=0.02, length=0.5):
    """A strummed chord: onsets a few ms apart, as a real pick produces."""
    return [
        {"start": start + i * spread, "end": start + length, "midi": m}
        for i, m in enumerate(midis)
    ]


class GroupingTests(unittest.TestCase):
    def test_a_strum_becomes_one_chord_not_six(self):
        events = stack([40, 47, 52, 56, 59, 64])
        groups = chords.group_simultaneities(events)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["note_count"], 6)

    def test_consecutive_eighths_stay_separate(self):
        events = [{"start": 0.0, "end": 0.2, "midi": 60},
                  {"start": 0.25, "end": 0.45, "midi": 62}]
        self.assertEqual(len(chords.group_simultaneities(events)), 2)

    def test_window_is_adjustable(self):
        events = [{"start": 0.0, "end": 0.2, "midi": 60},
                  {"start": 0.2, "end": 0.4, "midi": 64}]
        self.assertEqual(len(chords.group_simultaneities(events, window=0.05)), 2)
        self.assertEqual(len(chords.group_simultaneities(events, window=0.3)), 1)

    def test_a_fast_run_does_not_chain_into_one_chord(self):
        """Adjacent-gap chaining alone would swallow a whole scale run."""
        events = [{"start": i * 0.06, "end": i * 0.06 + 0.05, "midi": 60 + i}
                  for i in range(8)]
        groups = chords.group_simultaneities(events, window=0.08)
        self.assertGreater(len(groups), 1)
        self.assertTrue(all(g["note_count"] <= 4 for g in groups))

    def test_max_width_scales_with_the_window(self):
        events = [{"start": 0.0, "end": 0.2, "midi": 60},
                  {"start": 0.2, "end": 0.4, "midi": 64}]
        self.assertEqual(len(chords.group_simultaneities(events, window=0.3)), 1)

    def test_min_notes_filters_single_notes(self):
        events = stack([60, 64, 67]) + [{"start": 2.0, "end": 2.2, "midi": 72}]
        groups = chords.group_simultaneities(events, min_notes=2)
        self.assertEqual(len(groups), 1)

    def test_bass_is_the_lowest_note(self):
        groups = chords.group_simultaneities(stack([64, 60, 67]))
        self.assertEqual(groups[0]["bass"], 60)


class NamingTests(unittest.TestCase):
    def test_triads(self):
        self.assertEqual(chords.name_chord([60, 64, 67])["symbol"], "C")
        self.assertEqual(chords.name_chord([57, 60, 64])["symbol"], "Am")
        self.assertEqual(chords.name_chord([62, 65, 69])["symbol"], "Dm")

    def test_sevenths(self):
        self.assertEqual(chords.name_chord([55, 59, 62, 65])["symbol"], "G7")
        self.assertEqual(chords.name_chord([60, 64, 67, 71])["symbol"], "Cmaj7")

    def test_bass_decides_between_identical_note_sets(self):
        """A C E G is exactly Am7 and exactly C6 -- only the bass separates."""
        self.assertEqual(chords.name_chord([57, 60, 64, 67])["symbol"], "Am7")
        self.assertEqual(chords.name_chord([60, 64, 67, 69])["symbol"], "C6")

    def test_inversion_is_written_as_a_slash(self):
        self.assertEqual(chords.name_chord([52, 60, 67])["symbol"], "C/E")

    def test_power_chord(self):
        self.assertEqual(chords.name_chord([48, 55])["symbol"], "C5")

    def test_suspensions(self):
        self.assertEqual(chords.name_chord([60, 65, 67])["symbol"], "Csus4")
        self.assertEqual(chords.name_chord([60, 62, 67])["symbol"], "Csus2")

    def test_exact_flag_marks_a_clean_match(self):
        self.assertTrue(chords.name_chord([60, 64, 67])["exact"])

    def test_spurious_note_is_reported_not_hidden(self):
        # A transcription artefact should surface as an extra, not silently
        # push the name to some exotic chord.
        result = chords.name_chord([60, 64, 67, 61])
        self.assertFalse(result["exact"])
        self.assertTrue(result["extra"] or result["missing"])

    def test_single_pitch_class(self):
        self.assertEqual(chords.name_chord([60, 72])["quality"], "unison")

    def test_empty(self):
        self.assertIsNone(chords.name_chord([]))


class VoicingTests(unittest.TestCase):
    def test_open_c_shape(self):
        # C3 E3 G3 C4 E4 -> the standard x32010
        voicing = chords.voice_chord([48, 52, 55, 60, 64])
        self.assertEqual(voicing["shorthand"], "x32010")

    def test_open_g_shape(self):
        voicing = chords.voice_chord([43, 47, 50, 55, 59, 67])
        self.assertIsNotNone(voicing)
        self.assertEqual(len(voicing["positions"]), 6)

    def test_span_is_within_a_hand(self):
        voicing = chords.voice_chord([48, 52, 55, 60, 64])
        self.assertLessEqual(voicing["span"], chords.MAX_SPAN)

    def test_impossible_voicing_returns_none(self):
        """Seven notes cannot be one grip on six strings -- say so."""
        self.assertIsNone(chords.voice_chord([40, 42, 44, 46, 48, 50, 52]))

    def test_notes_below_the_guitar_are_unplayable(self):
        self.assertIsNone(chords.voice_chord([20, 24]))

    def test_shorthand_marks_unused_strings(self):
        voicing = chords.voice_chord([60, 64, 67])
        self.assertEqual(len(voicing["shorthand"].replace("(", "").replace(")", "")), 6)
        self.assertIn("x", voicing["shorthand"])

    def test_one_note_per_string(self):
        voicing = chords.voice_chord([48, 52, 55, 60, 64])
        used = [p["string"] for p in voicing["positions"]]
        self.assertEqual(len(used), len(set(used)))


class DiagramTests(unittest.TestCase):
    def test_diagram_has_six_string_rows(self):
        voicing = chords.voice_chord([48, 52, 55, 60, 64])
        rendered = chords.render_diagram(voicing, name="C")
        # header + 6 strings + fret-number footer
        self.assertEqual(len(rendered.splitlines()), 8)
        self.assertIn("C", rendered)

    def test_diagram_handles_no_voicing(self):
        self.assertIn("no single-position", chords.render_diagram(None))

    def test_chord_tab_has_six_rows(self):
        analysed = chords.analyze(stack([48, 52, 55, 60, 64]))
        self.assertEqual(len(chords.render_chord_tab(analysed).splitlines()), 6)


class ReportTests(unittest.TestCase):
    def test_progression_is_reported(self):
        events = (
            stack([48, 52, 55, 60, 64], start=0.0)
            + stack([45, 52, 57, 60, 64], start=1.0)
            + stack([53, 57, 60, 65], start=2.0)
        )
        report = chords.format_chords(chords.analyze(events))
        self.assertIn("Progression:", report)
        self.assertIn("C", report)
        self.assertIn("Am", report)
        self.assertIn("Tab:", report)
        self.assertIn("Shapes:", report)

    def test_single_line_material_says_so(self):
        self.assertIn("single-line", chords.format_chords([]))


class MusicXmlTests(unittest.TestCase):
    def _score(self, events, **kw):
        # min_notes=1 so single-note melodies notate too, as the CLI does.
        return musicxml.build(chords.analyze(events, min_notes=1), **kw)

    def test_output_is_well_formed(self):
        xml = self._score(stack([60, 64, 67]))
        ET.fromstring(xml)  # raises on malformed XML

    def test_carries_chord_symbols(self):
        xml = self._score(
            stack([60, 64, 67], start=0.0) + stack([57, 60, 64], start=1.0)
        )
        root = ET.fromstring(xml)
        texts = [h.find("kind").get("text") for h in root.iter("harmony")]
        self.assertIn("C", texts)
        self.assertIn("Am", texts)

    def test_stacked_notes_use_the_chord_element(self):
        """Without <chord/> the notes would notate as a sequence, not a stack."""
        root = ET.fromstring(self._score(stack([60, 64, 67])))
        notes = [n for n in root.iter("note") if n.find("rest") is None]
        self.assertEqual(len(notes), 3)
        self.assertEqual(sum(1 for n in notes if n.find("chord") is not None), 2)

    def test_title_is_escaped(self):
        xml = self._score(stack([60, 64]), title="Rock & Roll <demo>")
        ET.fromstring(xml)
        self.assertIn("&amp;", xml)

    def test_pitch_alter_for_black_keys(self):
        root = ET.fromstring(self._score(stack([61])))
        pitch = next(root.iter("pitch"))
        self.assertEqual(pitch.find("step").text, "C")
        self.assertEqual(pitch.find("alter").text, "1")

    def test_octave_numbering(self):
        root = ET.fromstring(self._score(stack([60])))
        self.assertEqual(next(root.iter("pitch")).find("octave").text, "4")

    def test_tempo_is_recorded(self):
        xml = self._score(stack([60]), bpm=92)
        self.assertIn('tempo="92"', xml)

    def test_gaps_become_rests(self):
        events = stack([60], start=0.0, length=0.25) + stack([64], start=2.0)
        root = ET.fromstring(self._score(events, bpm=120))
        self.assertTrue(any(n.find("rest") is not None for n in root.iter("note")))

    def test_long_passage_splits_into_measures(self):
        events = []
        for i in range(8):
            events += stack([60, 64, 67], start=i * 1.0)
        root = ET.fromstring(self._score(events, bpm=120))
        self.assertGreater(len(list(root.iter("measure"))), 1)

    def test_quantize_never_returns_zero(self):
        # A 5 ms blip must still occupy a notatable duration.
        self.assertGreaterEqual(musicxml.quantize(0.005, 120), 1)

    def test_note_type_mapping(self):
        self.assertEqual(musicxml.note_type(16), "whole")
        self.assertEqual(musicxml.note_type(4), "quarter")
        self.assertEqual(musicxml.note_type(1), "16th")


if __name__ == "__main__":
    unittest.main()
