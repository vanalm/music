"""Studio report tests — payload contract, page chrome, degradation.

The page renders its charts client-side from one inline ``window.SONG``
payload; the Python renderers remain the tested reference implementations
of the musical behaviour their JS ports mirror. Build-level tests therefore
assert two things: the payload carries the right data, and the static
chrome + inlined scripts wire the behavioural contract.
"""

import json
import os
import re
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


def song_of(html):
    """Extract and parse the inline window.SONG payload."""
    match = re.search(r"window\.SONG = (.*?);</script>", html, re.S)
    assert match, "no window.SONG payload in the page"
    return json.loads(match.group(1))


class PayloadTests(unittest.TestCase):
    """window.SONG is the page's whole data contract."""

    CHORDS = [
        {"start": 7.0, "end": 7.8, "symbol": "C", "shorthand": "x32010",
         "positions": [{"string": 5, "fret": 3}, {"string": 4, "fret": 2},
                       {"string": 2, "fret": 1}]},
        {"start": 32.0, "end": 32.9, "symbol": "G", "shorthand": "320003",
         "positions": [{"string": 6, "fret": 3}, {"string": 5, "fret": 2},
                       {"string": 1, "fret": 3}]},
    ]

    def test_sections_beats_and_facts_travel(self):
        song = song_of(report.build(payload()))
        self.assertEqual(len(song["sections"]), 4)
        self.assertEqual(song["sections"][2]["start"], 31.0)
        self.assertEqual(song["bpm"], 84)
        self.assertEqual(song["duration"], 74.0)
        self.assertEqual(song["missing"], ["bridge", "outro"])

    def test_notes_compact_to_rows(self):
        data = payload()
        data["stages"]["chords"] = {
            "chords": self.CHORDS,
            "notes": [{"start": 10.0, "end": 10.62, "midi": 64,
                       "velocity": 90}],
        }
        song = song_of(report.build(data))
        self.assertEqual(song["notes"], [[10.0, 10.62, 64, 90]])

    def test_chords_carry_fingering_with_midi(self):
        data = payload()
        data["stages"]["chords"] = {"chords": self.CHORDS}
        song = song_of(report.build(data))
        first = song["chords"][0]
        self.assertEqual(first["symbol"], "C")
        self.assertEqual(first["short"], "x32010")
        # [string, fret, midi]: string 5 fret 3 -> A2+3 = C3 = 48.
        self.assertIn([5, 3, 48], first["pos"])

    def test_canonical_shapes_ship_precomputed(self):
        data = payload()
        data["stages"]["chords"] = {"chords": self.CHORDS}
        song = song_of(report.build(data))
        self.assertIn("C", song["canon"])
        self.assertEqual(song["canon"]["C"]["short"], "x32010")

    def test_voice_absent_is_null_not_empty(self):
        song = song_of(report.build(payload()))
        self.assertIsNone(song["voice_notes"])

    def test_voice_notes_travel_when_present(self):
        data = payload()
        data["stages"]["voice"] = {
            "notes": [{"start": 1.0, "end": 1.5, "midi": 60}], "chords": [],
        }
        song = song_of(report.build(data))
        self.assertEqual(song["voice_notes"], [[1.0, 1.5, 60]])

    def test_lyric_segments_and_words_pass_through(self):
        data = payload()
        data["stages"]["lyrics"]["segments"] = [
            {"start": 7.5, "end": 11.0, "text": "walking down",
             "words": [{"start": 7.5, "end": 8.1, "text": "walking"},
                       {"start": 8.4, "end": 9.0, "text": "down"}]},
        ]
        song = song_of(report.build(data))
        self.assertEqual(song["lyric_segments"][0]["words"][1]["text"], "down")
        self.assertTrue(song["from_isolated_vocal"])

    def test_questions_and_norm_file_travel(self):
        data = payload()
        data["stages"]["normalize"]["file"] = "/tmp/p/normalized/song.wav"
        song = song_of(report.build(data))
        self.assertTrue(song["questions"])
        self.assertEqual(song["norm_file"], "/tmp/p/normalized/song.wav")

    def test_stems_reduce_to_names(self):
        song = song_of(report.build(payload()))
        self.assertEqual(song["stems"], ["vocals.wav", "other.wav"])


class StructureTests(unittest.TestCase):
    def test_timeline_component_is_on_the_page(self):
        html = report.build(payload())
        self.assertIn("<song-timeline>", html)
        self.assertIn("song-timeline .st-seg", html)   # its inlined CSS

    def test_missing_sections_are_called_out(self):
        html = report.build(payload())
        self.assertIn("not present yet", html)
        self.assertIn("bridge", html)

    def test_lyrics_provenance_is_stated(self):
        html = report.build(payload())
        self.assertIn("isolated vocal", html)

    def test_stems_listed_in_the_dock(self):
        html = report.build(payload())
        self.assertIn("Stems", html)
        self.assertIn("vocals · other", html)


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

    def test_no_chords_still_panels_per_section(self):
        # The roll and staff render from notes alone; sections without a
        # chord analysis still get their score panel.
        html = report.build(payload())
        self.assertEqual(html.count("<score-panel view="), 4)
        self.assertIn('data-start="0.0"', html)

    def test_no_lyrics_names_the_fix(self):
        data = payload()
        del data["stages"]["lyrics"]
        html = report.build(data)
        self.assertIn("No lyrics transcribed", html)
        self.assertIn("Whisper", html)


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


class ScorePanelsTests(unittest.TestCase):
    """The score: one static section skeleton per panel, charts client-side."""

    CHORDS = PayloadTests.CHORDS

    def _data(self):
        data = payload()
        data["stages"]["chords"] = {"chords": self.CHORDS}
        data["stages"]["normalize"]["file"] = "/tmp/p/normalized/song.wav"
        return data

    def test_sections_become_panels_with_score_elements(self):
        html = report.build(self._data())
        self.assertIn('<section class="panel" data-start="6.5"', html)
        self.assertIn('<score-panel view="roll" source="inst"', html)
        # A chip, a range, and the chord mini all in the header.
        self.assertIn('class="pchip"', html)
        self.assertIn("0:06–0:31", html)

    def test_chord_mini_summarises_the_progression(self):
        html = report.build(self._data())
        self.assertIn('class="pmini">C<', html)

    def test_lick_command_is_folded_away(self):
        html = report.build(self._data())
        self.assertIn('<details class="lickrow">', html)
        self.assertIn("music-stack lick --input", html)
        self.assertIn('class="copy"', html)

    def test_explicit_chords_param_still_wins(self):
        html = report.build(payload(), chords=self.CHORDS)
        song = song_of(html)
        self.assertEqual(song["chords"][0]["symbol"], "C")
        self.assertIn("x32010", html)  # canon in payload

    def test_tones_button_per_panel(self):
        # Panels group where chords were played: the verse and the chorus.
        html = report.build(self._data())
        self.assertEqual(html.count('class="tonesbtn"'), 2)


class EscapingTests(unittest.TestCase):
    def test_title_cannot_inject_markup(self):
        html = report.build({"title": "<script>alert(1)</script>", "stages": {}})
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)

    def test_payload_cannot_break_out_of_its_script_block(self):
        data = payload()
        data["stages"]["lyrics"]["text"] = "love & </script><b>hate</b>"
        html = report.build(data)
        # No "<" survives inside the JSON payload — < stays inert.
        blob = re.search(r"window\.SONG = (.*?);</script>", html, re.S).group(1)
        self.assertNotIn("<", blob)
        self.assertEqual(
            song_of(html)["lyrics_text"], "love & </script><b>hate</b>"
        )

    def test_lyrics_fallback_block_is_escaped(self):
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

    def test_wide_voicing_draws_instead_of_crashing(self):
        # A detected (not textbook) shape can span more than five frets.
        positions = [{"string": 6, "fret": 12}, {"string": 5, "fret": 0},
                     {"string": 1, "fret": 17}]
        svg = report.chord_svg(positions)
        self.assertIn("<svg", svg)

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


class BehaviouralContractTests(unittest.TestCase):
    """The interactions the page must keep, wherever they now live."""

    def test_keyboard_transport_is_wired(self):
        html = report.build(payload())
        for marker in ('e.code === "Space"', 'e.code === "ArrowRight"',
                       'e.code === "ArrowLeft"', 'e.code === "BracketLeft"'):
            self.assertIn(marker, html)
        self.assertIn("<kbd>space</kbd>", html)

    def test_speed_control_preserves_pitch(self):
        html = report.build(payload())
        self.assertIn("preservesPitch", html)
        self.assertIn('data-rate="0.5"', html)
        self.assertIn("same pitch, slower song", html)

    def test_speed_menu_starts_closed(self):
        html = report.build(payload())
        self.assertIn('<div id="ratemenu" hidden>', html)

    def test_ab_loop_is_wired(self):
        html = report.build(payload())
        for marker in ("sp-loop-point", 'e.code === "Escape"', "loopbadge",
                       "st-loop", "sp-loop"):
            self.assertIn(marker, html)
        self.assertIn("state.loopB != null && t >= state.loopB", html)
        self.assertIn("⌘", html)

    def test_drag_scrub_is_wired(self):
        html = report.build(payload())
        # score-panel emits scrub events; the app plays through them and
        # restores pause on release.
        for marker in ("sp-scrub-start", "sp-scrub-end", "wasPaused",
                       "pointerdown"):
            self.assertIn(marker, html)
        self.assertIn("drag = scrub", html)

    def test_alt_click_audition_is_wired(self):
        html = report.build(payload())
        self.assertIn("previewTone", html)
        self.assertIn("e.altKey", html)
        self.assertIn("AudioContext", html)

    def test_tones_playback_is_wired(self):
        html = report.build(payload())
        for marker in ("playTones", "stopTones", "DynamicsCompressor"):
            self.assertIn(marker, html)

    def test_tones_follow_the_source_toggle(self):
        html = report.build(payload())
        self.assertIn('state.source === "voice"', html)

    def test_plain_click_seeks_without_playing(self):
        html = report.build(payload())
        self.assertIn("sp-seek", html)
        # Seeking sets currentTime; only the play button / space starts
        # playback.
        self.assertIn("audio.currentTime = e.detail.t", html)

    def test_empty_area_clicks_resolve_by_position_not_section_start(self):
        # closest("[data-start]") must not escape the score-panel into the
        # section wrapper — that seeked every empty-area click (and both
        # ⌘-click loop points) to the section's beginning.
        html = report.build(payload())
        self.assertIn("if (timed && !self.contains(timed)) timed = null;",
                      html)

    def test_seq_chart_hit_tests_measure_from_the_svg(self):
        # Column x coordinates live in the SVG's pixel space; measuring
        # from the padded container skewed ⌥-clicks onto neighbours.
        html = report.build(payload())
        self.assertIn('m.inner.querySelector("svg")', html)

    def test_collision_layout_is_inlined(self):
        html = report.build(payload())
        for marker in ("batchLayoutWords", "batchThinNames", "neededPPS"):
            self.assertIn(marker, html)

    def test_word_timing_estimator_is_inlined(self):
        html = report.build(payload())
        self.assertIn("wordSegmentsSynced", html)

    def test_state_persists_across_openings(self):
        html = report.build(payload())
        self.assertIn("localStorage", html)
        self.assertIn("music-studio-v1", html)

    def test_theme_toggle_is_wired(self):
        html = report.build(payload())
        self.assertIn('id="themebtn"', html)
        self.assertIn('[data-theme="dark"]', html)


class StudioChromeTests(unittest.TestCase):
    def test_view_pills_offer_all_four_views(self):
        html = report.build(payload())
        for label in ("Piano roll", "Guitar tab", "Sheet music",
                      "Chord chart"):
            self.assertIn(label, html)
        self.assertIn('data-view="staff"', html)

    def test_source_pills_only_with_a_voice_transcription(self):
        html = report.build(payload())
        self.assertNotIn(">Voice<", html)
        data = payload()
        data["stages"]["voice"] = {"notes": [], "chords": []}
        html = report.build(data)
        self.assertIn('class="pill spill', html)
        self.assertIn(">Voice<", html)

    def test_dock_holds_transport_and_karaoke(self):
        html = report.build(payload())
        for marker in ('id="playbtn"', 'id="clocknow"', 'id="karaoke"',
                       'id="ratebtn"'):
            self.assertIn(marker, html)

    def test_now_playing_card_needs_chords(self):
        html = report.build(payload())
        self.assertNotIn("Now playing", html)
        data = payload()
        data["stages"]["chords"] = {"chords": PayloadTests.CHORDS}
        html = report.build(data)
        self.assertIn("Now playing", html)
        self.assertIn('id="nowgrip"', html)

    def test_shapes_card_counts_the_song(self):
        data = payload()
        data["stages"]["chords"] = {"chords": PayloadTests.CHORDS}
        html = report.build(data)
        self.assertIn("Shapes in this song", html)
        self.assertIn("2 total", html)
        self.assertIn("<chord-cards", html)

    def test_timed_lyrics_get_the_follow_window(self):
        data = payload()
        data["stages"]["lyrics"]["segments"] = [
            {"start": 7.5, "end": 11.0, "text": "walking down"},
        ]
        html = report.build(data)
        self.assertIn('id="lyricwin"', html)

    def test_untimed_lyrics_still_render_as_plain_text(self):
        html = report.build(payload())
        self.assertIn('<pre class="lyrics">', html)

    def test_questions_render_in_their_card(self):
        html = report.build(payload())
        self.assertIn("To finish this", html)
        self.assertIn('class="question"', html)

    def test_about_line_names_the_tools(self):
        html = report.build(payload())
        for tool in ("ffmpeg", "Demucs", "allin1", "basic-pitch"):
            self.assertIn(tool, html)

    def test_narrow_screens_keep_the_transport_in_reach(self):
        # On one-column layouts the player card becomes a sticky top bar
        # instead of sinking below the whole score.
        html = report.build(payload())
        self.assertIn('class="card playercard"', html)
        self.assertIn("order:-1; position:sticky", html)

    def test_design_tokens_and_dark_theme(self):
        html = report.build(payload())
        self.assertIn("--c-accent:#b4502e", html)
        self.assertIn("--c-note:#46607e", html)
        self.assertIn("--c-accent:#e07a50", html)   # dark accent

    def test_both_libraries_are_inlined(self):
        html = report.build(payload())
        self.assertIn("window.ReportLib", html)
        self.assertIn('customElements.define("score-panel"', html)
        self.assertIn('customElements.define("song-timeline"', html)
        self.assertIn('customElements.define("chord-cards"', html)
        # No external requests: every script is inline.
        self.assertNotIn("<script src=", html)


class NoteRollTests(unittest.TestCase):
    """The reference renderer: every note, its time, its pitch."""

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


class WordTimingTests(unittest.TestCase):
    """The word-timing reference implementation the JS port mirrors."""

    def test_word_segments_interpolate_inside_a_line(self):
        segs = [{"start": 10.0, "end": 14.0, "text": "walking down"}]
        words = report.word_segments(segs)
        self.assertEqual([w["text"] for w in words], ["walking", "down"])
        self.assertEqual(words[0]["start"], 10.0)
        # "walking" is the longer word, so it takes the larger share.
        self.assertGreater(words[1]["start"], 12.0)
        self.assertEqual(words[-1]["end"], 14.0)

    def test_word_segments_prefer_real_timestamps(self):
        segs = [{
            "start": 10.0, "end": 14.0, "text": "walking down",
            "words": [
                {"start": 10.5, "end": 10.9, "text": "walking"},
                {"start": 12.2, "end": 12.5, "text": "down"},
            ],
        }]
        words = report.word_segments(segs)
        self.assertEqual(words[0]["start"], 10.5)
        self.assertEqual(words[1]["start"], 12.2)

    def test_word_segments_snap_to_vocal_onsets(self):
        # One Whisper line, 10–20s, but the voice stopped singing at 14:
        # words must spread over the sung span only, and land on attacks.
        segs = [{"start": 10.0, "end": 20.0, "text": "walking down slow"}]
        onsets = [10.0, 11.6, 13.4]
        words = report.word_segments(segs, onsets=onsets)
        self.assertEqual(words[0]["start"], 10.0)
        self.assertEqual(words[1]["start"], 11.6)   # snapped to the attack
        self.assertEqual(words[2]["start"], 13.4)
        # Nothing drifts into the six seconds of trailing accompaniment.
        self.assertLessEqual(words[-1]["end"], 14.01)

    def test_word_starts_stay_ordered_after_snapping(self):
        segs = [{"start": 10.0, "end": 12.0, "text": "a b c d"}]
        # One attack sits amid the words: neighbours must not reorder.
        words = report.word_segments(segs, onsets=[10.9])
        starts = [w["start"] for w in words]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(len(set(starts)), len(starts))

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

    def test_lines_alternate_lanes(self):
        segs = [
            {"start": 10.0, "end": 11.0, "text": "one", "line": 0},
            {"start": 11.0, "end": 12.0, "text": "two", "line": 1},
        ]
        html = report._words_row(segs, 8.0, 40.0)
        self.assertIn('class="word"', html)
        self.assertIn('class="word l1"', html)


class StaffTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
