"""HTML report tests — structure, escaping, interactivity hooks, degradation."""

import os
import subprocess
import tempfile
import unittest
from unittest import mock

from music_stack import audio, chords, report

HAS_FFMPEG = bool(audio.which("ffmpeg"))
requires_ffmpeg = unittest.skipUnless(
    HAS_FFMPEG, "ffmpeg not installed; run ./scripts/bootstrap-macos.sh"
)


def tone(path, seconds=1):
    subprocess.run(
        [
            audio.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration={}".format(seconds),
            path,
        ],
        check=True,
    )
    return path


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


class PreviewEmbedTests(unittest.TestCase):
    """The page embeds an AAC preview when it can, and says so when it can't."""

    def test_missing_file_reports_why(self):
        data_uri, note = report.preview_audio("/nope/demo.wav")
        self.assertIsNone(data_uri)
        self.assertIn("not found", note)

    def test_no_ffmpeg_reports_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "demo.wav")
            open(path, "wb").close()
            with mock.patch.object(report.audio_mod, "which", return_value=None):
                data_uri, note = report.preview_audio(path)
        self.assertIsNone(data_uri)
        self.assertIn("ffmpeg", note)

    @requires_ffmpeg
    def test_embeds_small_audio_as_data_uri(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = tone(os.path.join(tmp, "demo.wav"))
            data_uri, note = report.preview_audio(path)
        self.assertTrue(data_uri and data_uri.startswith("data:audio/mp4;base64,"))
        self.assertIn("embedded", note)

    @requires_ffmpeg
    def test_oversize_preview_degrades_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = tone(os.path.join(tmp, "demo.wav"))
            data_uri, note = report.preview_audio(path, max_bytes=10)
            self.assertIsNone(data_uri)
            self.assertIn("too large", note)

            data = payload()
            data["project"] = tmp
            with mock.patch.object(
                report, "preview_audio",
                return_value=(None, "preview is 99 MB, too large to embed"),
            ):
                html = report.build(data, audio_path=path)
        self.assertIn('src="demo.wav"', html)
        self.assertIn("not embedded", html)

    @requires_ffmpeg
    def test_build_prefers_the_embedded_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = tone(os.path.join(tmp, "demo.wav"))
            html = report.build(payload(), audio_path=path)
        self.assertIn("data:audio/mp4;base64,", html)
        self.assertNotIn("not embedded", html)


class ChordsFromResultTests(unittest.TestCase):
    """The report shows what to play without anyone passing chords= by hand."""

    CHORDS = [
        {"start": 7.0, "end": 7.8, "symbol": "C", "shorthand": "x32010",
         "positions": [{"string": 5, "fret": 3}, {"string": 4, "fret": 2},
                       {"string": 2, "fret": 1}]},
        {"start": 32.0, "end": 32.9, "symbol": "G", "shorthand": "320003",
         "positions": [{"string": 6, "fret": 3}, {"string": 5, "fret": 2},
                       {"string": 1, "fret": 3}]},
    ]

    def test_progression_and_boxes_render_from_the_stages_dict(self):
        data = payload()
        data["stages"]["chords"] = {"chords": self.CHORDS}
        data["stages"]["normalize"]["file"] = "/tmp/p/normalized/song.wav"
        html = report.build(data)
        self.assertIn('class="progression"', html)
        self.assertIn("verse", html)
        self.assertIn("x32010", html)          # chord box card
        self.assertIn("music-stack lick --input", html)

    def test_section_panels_are_wired_for_live_playback(self):
        data = payload()
        data["stages"]["chords"] = {"chords": self.CHORDS}
        html = report.build(data)
        # A chip per played chord, timed so the script can light it up.
        self.assertIn('<span class="chip" data-start="7.0" data-end="7.8">C', html)
        # Each section panel carries its span and a tab chart.
        self.assertIn('<details class="panel" data-start="6.5"', html)
        self.assertIn('<pre class="tab">', html)
        self.assertIn("e|", html)

    def test_explicit_chords_param_still_wins(self):
        html = report.build(payload(), chords=self.CHORDS)
        self.assertIn("x32010", html)

    def test_no_chords_no_section(self):
        html = report.build(payload())
        self.assertNotIn('class="progression"', html)


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
        self.assertNotIn("<h2>Play along</h2>", html)

    def test_keyboard_controls_are_wired(self):
        html = report.build(payload())
        self.assertIn('e.code === "Space"', html)
        self.assertIn('e.code === "ArrowRight"', html)
        self.assertIn('e.code === "ArrowLeft"', html)

    def test_notes_carry_midi_and_time_for_alt_click_to_hear(self):
        roll = report.note_roll(
            [{"start": 10.0, "end": 10.4, "midi": 64}], 8.0, 40.0
        )
        self.assertIn('data-midi="64"', roll)
        self.assertIn('data-start="10.0"', roll)
        svg, _t, _x, mids = report.staff_svg(
            [
                {"start": 10.0, "end": 10.4, "midi": 64},
                {"start": 10.03, "end": 10.4, "midi": 60},
            ],
            8.0, 40.0,
        )
        self.assertIn('data-midi="64"', svg)
        # The whole simultaneous moment, for alt-clicks that miss a note.
        self.assertEqual(sorted(mids[0]), [60, 64])
        self.assertEqual(len(mids), 1)

    def test_interaction_contract_in_the_script(self):
        html = report.build(payload())
        # Alt previews; a plain click moves the playhead without playing.
        self.assertIn("e.altKey", html)
        self.assertIn("only moves the playhead", html)

    def test_tab_and_chord_cells_carry_string_midi_pairs(self):
        data = payload()
        data["stages"]["chords"] = {
            "chords": [
                {"start": 10.0, "end": 10.9, "symbol": "C",
                 "shorthand": "x32010",
                 "positions": [{"string": 5, "fret": 3}]},
            ],
            "notes": [{"start": 10.0, "end": 10.4, "midi": 64}],
        }
        html = report.build(data)
        # Guitar tab: E4 open high e -> string 1, midi 64.
        self.assertIn('data-cells="1:64"', html)
        # Chord chart: C's textbook grip starts on string 5 fret 3 -> C3.
        self.assertIn("5:48", html)
        self.assertIn("previewTone", html)
        self.assertIn("AudioContext", html)

    def test_ab_loop_is_wired(self):
        html = report.build(payload())
        # cmd-click sets the points, escape clears, the region is shaded,
        # playback and scrubbing wrap at the loop end.
        self.assertIn("e.metaKey", html)
        self.assertIn('e.code === "Escape"', html)
        self.assertIn("loop-shade", html)
        self.assertIn('id="loopbadge"', html)
        self.assertIn("loop.b !== null && player.currentTime >= loop.b",
                      html)
        self.assertIn("⌘", html)

    def test_wide_voicing_draws_instead_of_crashing(self):
        # A detected (not textbook) shape can span more than five frets.
        positions = [{"string": 6, "fret": 12}, {"string": 5, "fret": 0},
                     {"string": 1, "fret": 17}]
        svg = report.chord_svg(positions)
        self.assertIn("<svg", svg)


class PlayerWiringTests(unittest.TestCase):
    def test_playhead_and_seek_script_present(self):
        html = report.build(payload())
        self.assertIn('id="playhead"', html)
        self.assertIn("timeupdate", html)
        self.assertIn("dataset.start", html)

    def test_light_professional_palette(self):
        # The page deliberately commits to one warm editorial look:
        # paper ground, terracotta accents, slate-blue notes.
        html = report.build(payload())
        self.assertIn("--card: #fffdf8", html)
        self.assertIn("--accent: #bc5a3c", html)
        self.assertIn("--note: #54677d", html)

    def test_keyboard_hints_are_shown(self):
        self.assertIn("<kbd>space</kbd>", report.build(payload()))


class NoteRollTests(unittest.TestCase):
    """The accuracy-first view: every note, its time, its pitch."""

    EVENTS = [
        {"start": 10.0, "end": 10.4, "midi": 64, "velocity": 90},   # E4 fill
        {"start": 10.5, "end": 10.7, "midi": 67, "velocity": 60},   # G4 fill
        {"start": 12.0, "end": 13.5, "midi": 48, "velocity": 100},  # C3 chord
    ]

    def test_one_rect_per_note_with_names(self):
        svg = report.note_roll(self.EVENTS, 8.0, 40.0)
        self.assertEqual(svg.count('class="nr"'), 3)
        self.assertIn("E4", svg)
        self.assertIn("G4", svg)

    def test_notes_outside_the_window_are_excluded(self):
        svg = report.note_roll(self.EVENTS, 0.0, 9.0)
        self.assertEqual(svg, "")

    def test_quiet_notes_render_fainter(self):
        svg = report.note_roll(self.EVENTS, 8.0, 40.0)
        # velocity 60 -> lower opacity than velocity 100
        self.assertIn('opacity="0.66"', svg)
        self.assertIn('opacity="0.86"', svg)

    def test_note_names_align_with_their_moment_in_the_roll(self):
        html = report._names_row(self.EVENTS, 8.0, 40.0)
        # Two quick fill notes then the chord note, in playback order.
        self.assertLess(html.index("E4"), html.index("G4"))
        self.assertLess(html.index("G4"), html.index("C3"))
        self.assertIn('data-start="10.0"', html)
        # 10.0s into an 8..40s window = 6.25% across, matching the roll.
        self.assertIn('style="left:6.25%"', html)
        self.assertIn("namesline", html)

    def test_simultaneous_notes_share_a_column_highest_first(self):
        events = [
            {"start": 5.0, "end": 6.0, "midi": 48},
            {"start": 5.03, "end": 6.0, "midi": 64},
        ]
        cols = report.name_columns(events)
        self.assertEqual(len(cols), 1)
        html = report._names_row(events, 4.0, 10.0)
        self.assertLess(html.index("E4"), html.index("C3"))

    def test_view_selector_offers_all_four_views(self):
        data = payload()
        data["stages"]["chords"] = {
            "chords": [
                {"start": 10.0, "end": 10.9, "symbol": "C",
                 "shorthand": "x32010",
                 "positions": [{"string": 5, "fret": 3}]},
            ],
            "notes": self.EVENTS,
        }
        html = report.build(data)
        for label in ("Piano roll", "Guitar tab", "Sheet music",
                      "Chord chart"):
            self.assertIn(label, html)
        self.assertIn('data-view="gtab"', html)
        self.assertIn("staffwrap", html)
        # One global switcher in the player bar, not one per section.
        self.assertEqual(html.count('class="vtabs"'), 1)

    def test_timed_lyrics_render_as_seekable_lines_with_karaoke(self):
        data = payload()
        data["stages"]["lyrics"]["segments"] = [
            {"start": 7.5, "end": 11.0, "text": "walking down"},
            {"start": 12.0, "end": 15.0, "text": "to the water line"},
        ]
        html = report.build(data)
        self.assertIn('class="lline" data-start="7.5"', html)
        self.assertIn("walking down", html)
        self.assertIn('id="karaoke"', html)

    def test_untimed_lyrics_still_render_as_plain_text(self):
        html = report.build(payload())
        self.assertIn('<pre class="lyrics">', html)

    def test_words_align_under_the_roll(self):
        segs = [{"start": 10.0, "end": 14.0, "text": "walking down"}]
        html = report._words_row(segs, 8.0, 40.0)
        self.assertIn('style="left:6.25%"', html)
        self.assertIn('class="word"', html)
        self.assertEqual(report._words_row(segs, 20.0, 30.0), "")

    def test_words_land_on_sequence_columns(self):
        segs = [{"start": 11.0, "end": 12.0, "text": "walking"}]
        # Staff mode: halfway between the columns at 10s and 12s.
        html = report._words_row(
            segs, 8.0, 40.0, times=[10.0, 12.0], xs=[100.0, 200.0]
        )
        self.assertIn('style="left:150.0px"', html)
        # Tab mode: same interpolation, in monospace columns.
        html = report._words_row(segs, 8.0, 40.0, times=[10.0, 12.0])
        self.assertIn('style="left:6.0ch"', html)

    def test_words_appear_on_tab_and_staff_charts(self):
        data = payload()
        data["stages"]["lyrics"]["segments"] = [
            {"start": 10.2, "end": 11.5, "text": "walking down"},
        ]
        data["stages"]["chords"] = {
            "chords": [
                {"start": 10.0, "end": 10.9, "symbol": "C",
                 "shorthand": "x32010",
                 "positions": [{"string": 5, "fret": 3}]},
            ],
            "notes": self.EVENTS,
        }
        html = report.build(data)
        # One aligned words row per surface: roll + each tab variant + staff.
        self.assertGreaterEqual(html.count('class="words"'), 3)

    def test_info_card_names_the_tools(self):
        html = report.build(payload())
        self.assertIn('id="infobtn"', html)
        for tool in ("ffmpeg", "Demucs", "allin1", "basic-pitch"):
            self.assertIn(tool, html)

    def test_staff_is_a_grand_staff_with_bass_clef(self):
        events = [
            {"start": 10.0, "end": 10.4, "midi": 63},  # Eb4 -> flat, treble
            {"start": 11.0, "end": 11.4, "midi": 48},  # C3 -> bass staff
            {"start": 12.0, "end": 12.4, "midi": 36},  # C2 -> ledger below
        ]
        svg, times, xs, _mids = report.staff_svg(events, 8.0, 40.0)
        self.assertEqual(svg.count('class="sn"'), 3)
        self.assertIn("♭", svg)
        self.assertIn("\U0001d11e", svg)   # treble clef
        self.assertIn("\U0001d122", svg)   # bass clef
        self.assertIn('class="ledger"', svg)
        # Ten staff lines plus the connecting barline.
        self.assertEqual(svg.count('class="sline"'), 11)

    def test_staff_columns_are_evenly_spaced_with_known_x(self):
        events = [
            {"start": 10.0, "end": 10.4, "midi": 63},
            {"start": 11.0, "end": 11.4, "midi": 48},
            {"start": 12.0, "end": 12.4, "midi": 36},
        ]
        svg, times, xs, _mids = report.staff_svg(events, 8.0, 40.0)
        self.assertEqual(times, [10.0, 11.0, 12.0])
        # Engraving spacing: equal steps regardless of the time gaps.
        self.assertEqual(xs[1] - xs[0], xs[2] - xs[1])
        # The playhead can land exactly on a notehead: xs match the cx.
        self.assertIn('cx="{:.1f}"'.format(xs[0]), svg)

    def test_simultaneous_staff_notes_share_a_column(self):
        events = [
            {"start": 10.0, "end": 11.0, "midi": 48},
            {"start": 10.03, "end": 11.0, "midi": 64},
        ]
        _svg, times, xs, _mids = report.staff_svg(events, 8.0, 40.0)
        self.assertEqual(len(times), 1)
        self.assertEqual(len(xs), 1)

    def test_beat_grid_adds_time_signature_barlines_and_beams(self):
        beats = [8.0 + 0.5 * i for i in range(20)]      # 120 BPM grid
        downbeats = [8.0, 10.0, 12.0, 14.0, 16.0]       # 4 beats per bar
        events = [
            # Two eighths in one beat: should beam together.
            {"start": 10.0, "end": 10.2, "midi": 64},
            {"start": 10.25, "end": 10.45, "midi": 67},
            # A quarter: plain stem, no flag.
            {"start": 10.5, "end": 11.0, "midi": 65},
            # An eighth cut off by the barline: no partner to beam with,
            # so it gets a flag.
            {"start": 11.75, "end": 11.9, "midi": 67},
            # Next measure: a quarter, then a half -> open head.
            {"start": 12.0, "end": 12.2, "midi": 64},
            {"start": 12.5, "end": 13.5, "midi": 60},
        ]
        svg, _t, _x, _m = report.staff_svg(
            events, 8.0, 16.0, beats=beats, downbeats=downbeats
        )
        self.assertEqual(svg.count('class="tsig"'), 4)  # 4/4 on both staves
        self.assertIn(">4</text>", svg)
        self.assertIn('class="barline"', svg)
        self.assertIn('class="beam"', svg)
        self.assertIn('class="flag"', svg)
        self.assertIn('class="sn open"', svg)           # the half note
        self.assertIn('class="stem"', svg)

    def test_no_beat_grid_stays_unmetered(self):
        svg, _t, _x, _m = report.staff_svg(
            [{"start": 10.0, "end": 10.4, "midi": 60}], 8.0, 40.0
        )
        for cls in ("tsig", "barline", "beam", "flag", "stem"):
            self.assertNotIn('class="{}"'.format(cls), svg)

    def test_middle_c_takes_one_ledger_not_a_tower(self):
        svg, _times, _xs, _m = report.staff_svg(
            [{"start": 10.0, "end": 10.4, "midi": 60}], 8.0, 40.0
        )
        self.assertEqual(svg.count('class="ledger"'), 1)

    def test_staff_wrap_carries_column_coordinates(self):
        data = payload()
        data["stages"]["chords"] = {
            "chords": [
                {"start": 10.0, "end": 10.9, "symbol": "C",
                 "shorthand": "x32010",
                 "positions": [{"string": 5, "fret": 3}]},
            ],
            "notes": self.EVENTS,
        }
        html = report.build(data)
        self.assertIn('class="tabwrap staffwrap"', html)
        self.assertIn("data-xs=", html)

    def test_tab_offers_alternate_positions_with_a_selector(self):
        # A midrange melody is playable in several neck positions, so the
        # view carries multiple deduped fingerings and a selector.
        data = payload()
        data["stages"]["chords"] = {
            "chords": [
                {"start": 10.0, "end": 10.9, "symbol": "C",
                 "shorthand": "x32010",
                 "positions": [{"string": 5, "fret": 3}]},
            ],
            "notes": [
                {"start": 10.0, "end": 10.4, "midi": 64},
                {"start": 10.5, "end": 10.9, "midi": 67},
                {"start": 11.0, "end": 11.4, "midi": 60},
            ],
        }
        html = report.build(data)
        self.assertIn('class="posbar"', html)
        self.assertGreaterEqual(html.count('class="tabvar'), 2)
        self.assertIn(">5th<", html)

    def test_position_seed_moves_the_fingering_up_the_neck(self):
        from music_stack import notes as notes_mod
        events = [{"start": 0.0, "end": 0.5, "midi": 64}]  # E4
        low = notes_mod.choose_positions(
            events, strings=(1, 2, 3, 4, 5, 6))
        high = notes_mod.choose_positions(
            events, strings=(1, 2, 3, 4, 5, 6), prefer_fret=9)
        self.assertEqual(low[0]["fret"], 0)     # open high E
        self.assertEqual(high[0]["fret"], 9)    # same E4 on the G string
        self.assertEqual(high[0]["string"], 3)

    def test_tab_views_carry_note_times_for_the_playhead(self):
        data = payload()
        data["stages"]["chords"] = {
            "chords": [
                {"start": 10.0, "end": 10.9, "symbol": "C",
                 "shorthand": "x32010",
                 "positions": [{"string": 5, "fret": 3}]},
            ],
            "notes": self.EVENTS,
        }
        html = report.build(data)
        self.assertIn('data-times="10.0,10.5,12.0"', html)
        self.assertIn('class="roll-line tab-line"', html)

    def test_rolls_appear_in_section_panels(self):
        data = payload()
        data["stages"]["chords"] = {
            "chords": [
                {"start": 10.0, "end": 10.9, "symbol": "C",
                 "shorthand": "x32010",
                 "positions": [{"string": 5, "fret": 3}]},
            ],
            "notes": self.EVENTS,
        }
        html = report.build(data)
        self.assertIn('class="rollwrap" data-start="6.5"', html)
        self.assertIn('class="roll-line"', html)


if __name__ == "__main__":
    unittest.main()
