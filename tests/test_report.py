"""HTML report tests — structure, escaping, interactivity hooks, degradation."""

import unittest

from music_stack import chords, report


def payload(**overrides):
    base = {
        "title": "Kaimana Nights",
        "stages": {
            "normalize": {
                "summary": {"codec": "alac", "sample_rate": 48000,
                            "duration_seconds": 74.0}
            },
            "structure": {
                "summary": {
                    "bpm": 84, "duration_seconds": 74.0, "section_count": 4,
                    "missing": ["bridge", "outro"],
                    "sections": [
                        {"label": "intro", "start": 0.0, "end": 6.5, "seconds": 6.5},
                        {"label": "verse", "start": 6.5, "end": 31.0, "seconds": 24.5},
                        {"label": "chorus", "start": 31.0, "end": 52.0, "seconds": 21.0},
                        {"label": "verse", "start": 52.0, "end": 74.0, "seconds": 22.0},
                    ],
                }
            },
            "lyrics": {"from_isolated_vocal": True, "text": "walking down"},
            "stems": {"files": ["stems/vocals.wav", "stems/other.wav"]},
        },
        "skipped": [],
    }
    base.update(overrides)
    return base


class StructureTests(unittest.TestCase):
    def test_sections_become_clickable_segments(self):
        html = report.build(payload())
        self.assertIn('data-start="31.0"', html)
        self.assertEqual(html.count('class="seg"'), 4)

    def test_segment_widths_are_proportional(self):
        html = report.build(payload())
        # The chorus is 21/74 of the song ≈ 28.378%
        self.assertIn("width:28.378%", html)

    def test_missing_sections_render_as_chips(self):
        html = report.build(payload())
        self.assertIn("Not present yet", html)
        self.assertIn("bridge", html)

    def test_lyrics_and_provenance(self):
        html = report.build(payload())
        self.assertIn("walking down", html)
        self.assertIn("isolated vocal stem", html)

    def test_stems_link_by_relative_name(self):
        html = report.build(payload())
        self.assertIn('href="vocals.wav"', html)


class DegradationTests(unittest.TestCase):
    """A sparse analysis must produce a sparse page, not a broken one."""

    def test_no_structure_says_how_to_get_it(self):
        data = payload()
        del data["stages"]["structure"]
        html = report.build(data)
        self.assertIn("allin1", html)

    def test_empty_payload_still_renders(self):
        html = report.build({"title": "Empty", "stages": {}})
        self.assertIn("<html", html)
        self.assertIn("Empty", html)

    def test_no_audio_is_stated_not_silent(self):
        html = report.build(payload(), audio_path=None)
        self.assertIn("No audio available", html)

    def test_missing_audio_file_degrades_to_relative_src(self):
        html = report.build(payload(), audio_path="/nope/demo.wav")
        # Falls back to a relative filename source rather than nothing.
        self.assertIn('src="demo.wav"', html)


class EscapingTests(unittest.TestCase):
    def test_title_cannot_inject_markup(self):
        html = report.build({"title": "<script>alert(1)</script>", "stages": {}})
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)

    def test_lyrics_are_escaped(self):
        data = payload()
        data["stages"]["lyrics"]["text"] = "love & <hate>"
        html = report.build(data)
        self.assertIn("love &amp; &lt;hate&gt;", html)


class ChordSvgTests(unittest.TestCase):
    def _voicing(self, midis):
        return chords.voice_chord(midis)

    def test_open_c_draws_dots_and_marks(self):
        v = self._voicing([48, 52, 55, 60, 64])  # x32010
        svg = report.chord_svg(v["positions"])
        self.assertIn("<svg", svg)
        # x on the unused low E, two fretted dots minimum, open circles.
        self.assertIn('class="mark"', svg)
        self.assertIn('class="dot"', svg)
        self.assertIn('class="open"', svg)

    def test_chords_section_renders_each_shape_once(self):
        v = self._voicing([48, 52, 55, 60, 64])
        chord_list = [
            {"symbol": "C", "shorthand": v["shorthand"], "positions": v["positions"]},
            {"symbol": "C", "shorthand": v["shorthand"], "positions": v["positions"]},
        ]
        html = report.build(payload(), chords=chord_list)
        self.assertEqual(html.count('<figure class="card">'), 1)

    def test_no_chords_no_section(self):
        html = report.build(payload(), chords=[])
        self.assertNotIn("<h2>Chords</h2>", html)


class PlayerWiringTests(unittest.TestCase):
    def test_playhead_and_seek_script_present(self):
        html = report.build(payload())
        self.assertIn('id="playhead"', html)
        self.assertIn("timeupdate", html)
        self.assertIn("dataset.start", html)

    def test_dark_mode_palette(self):
        self.assertIn("prefers-color-scheme:dark", report.build(payload()))


if __name__ == "__main__":
    unittest.main()
