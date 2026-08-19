"""Tests for the one-command pipeline and the songwriting brief."""

import os
import tempfile
import unittest
from pathlib import Path

from music_stack import brief, local_tools


def result_with(structure=None, lyrics=None, skipped=(), stems=None):
    """Build an analyze() result without needing any tool installed."""
    stages = {}
    if structure is not None:
        stages["structure"] = {"summary": structure}
    if lyrics is not None:
        stages["lyrics"] = lyrics
    if stems is not None:
        stages["stems"] = stems
    return {
        "title": "Working Title",
        "slug": "working-title",
        "project": "/tmp/p",
        "source": "/tmp/demo.m4a",
        "stages": stages,
        "skipped": list(skipped),
    }


FULL_STRUCTURE = {
    "bpm": 92,
    "arrangement": "intro → verse → chorus → verse → chorus → outro",
    "duration_seconds": 180.0,
    "section_count": 6,
    "missing": ["bridge"],
    "sections": [
        {"label": "intro", "start": 0.0, "end": 8.0, "seconds": 8.0},
        {"label": "verse", "start": 8.0, "end": 40.0, "seconds": 32.0},
        {"label": "chorus", "start": 40.0, "end": 70.0, "seconds": 30.0},
        {"label": "verse", "start": 70.0, "end": 110.0, "seconds": 40.0},
        {"label": "chorus", "start": 110.0, "end": 160.0, "seconds": 50.0},
        {"label": "outro", "start": 160.0, "end": 180.0, "seconds": 20.0},
    ],
}


class RenderTests(unittest.TestCase):
    def test_includes_tempo_arrangement_and_table(self):
        out = brief.render(result_with(structure=FULL_STRUCTURE))
        self.assertIn("# Working Title", out)
        self.assertIn("92 BPM", out)
        self.assertIn("intro → verse → chorus", out)
        self.assertIn("| Section | Start | Length |", out)
        self.assertIn("| chorus | 0:40 | 30.0s |", out)

    def test_calls_out_missing_sections(self):
        out = brief.render(result_with(structure=FULL_STRUCTURE))
        self.assertIn("**Not present yet:** bridge", out)

    def test_notes_when_lyrics_came_from_the_full_mix(self):
        out = brief.render(
            result_with(
                lyrics={"text": "some words here", "from_isolated_vocal": False}
            )
        )
        self.assertIn("full mix", out)
        self.assertIn("some words here", out)

    def test_notes_when_lyrics_came_from_an_isolated_stem(self):
        out = brief.render(
            result_with(lyrics={"text": "clean words", "from_isolated_vocal": True})
        )
        self.assertIn("isolated vocal stem", out)

    def test_reports_skipped_stages_with_the_fix(self):
        out = brief.render(result_with(skipped=["stems", "lyrics"]))
        self.assertIn("stems, lyrics", out)
        self.assertIn("local doctor", out)

    def test_renders_with_no_stages_at_all(self):
        # A machine with only ffmpeg still gets a readable brief.
        out = brief.render(result_with())
        self.assertIn("# Working Title", out)
        self.assertIn("To finish this", out)


class QuestionTests(unittest.TestCase):
    """The questions must follow from the analysis, not be boilerplate."""

    def test_missing_chorus_is_called_out(self):
        s = dict(FULL_STRUCTURE, missing=["chorus", "bridge"])
        qs = " ".join(brief.questions(result_with(structure=s)))
        self.assertIn("no identifiable chorus", qs)

    def test_bridge_question_suppressed_when_chorus_also_missing(self):
        # Asking about a bridge is noise when the hook itself isn't written.
        s = dict(FULL_STRUCTURE, missing=["chorus", "bridge"])
        qs = " ".join(brief.questions(result_with(structure=s)))
        self.assertNotIn("No bridge", qs)

    def test_bridge_question_appears_when_only_bridge_missing(self):
        qs = " ".join(brief.questions(result_with(structure=FULL_STRUCTURE)))
        self.assertIn("No bridge", qs)

    def test_single_verse_prompts_for_a_second(self):
        s = dict(
            FULL_STRUCTURE,
            sections=[{"label": "verse", "start": 0, "end": 30, "seconds": 30}],
            missing=[],
        )
        qs = " ".join(brief.questions(result_with(structure=s)))
        self.assertIn("Only one verse", qs)

    def test_short_sketch_is_flagged(self):
        s = dict(FULL_STRUCTURE, duration_seconds=45.0, missing=[])
        qs = " ".join(brief.questions(result_with(structure=s)))
        self.assertIn("sketch, not an arrangement", qs)

    def test_sparse_lyrics_flagged(self):
        qs = " ".join(
            brief.questions(result_with(lyrics={"text": "just a few words sung"}))
        )
        self.assertIn("still", qs)

    def test_complete_song_gets_a_different_prompt(self):
        s = dict(FULL_STRUCTURE, missing=[])
        qs = " ".join(brief.questions(result_with(structure=s)))
        self.assertIn("structure is complete", qs)

    def test_always_ends_with_the_next_action(self):
        qs = brief.questions(result_with())
        self.assertIn("Paste this brief", qs[-1])


class DryRunTests(unittest.TestCase):
    def test_plans_without_running_anything(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "demo.m4a")
            Path(src).write_bytes(b"fake")
            root = os.path.join(tmp, "projects")
            result = brief.analyze(root, src, dry_run=True, log=lambda *_a: None)

        self.assertEqual(result["slug"], "demo")
        self.assertIn("normalize", result["stages"])
        # Nothing was transcoded or transcribed.
        self.assertNotIn("summary", result["stages"]["normalize"])

    def test_title_derived_from_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "my_new_song.m4a")
            Path(src).write_bytes(b"fake")
            result = brief.analyze(
                os.path.join(tmp, "p"), src, dry_run=True, log=lambda *_a: None
            )
        self.assertEqual(result["title"], "My New Song")

    def test_explicit_title_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "vm0001.m4a")
            Path(src).write_bytes(b"fake")
            result = brief.analyze(
                os.path.join(tmp, "p"), src, title="Hold The Line",
                dry_run=True, log=lambda *_a: None,
            )
        self.assertEqual(result["slug"], "hold-the-line")

    def test_missing_input_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                brief.analyze(tmp, "/nope/missing.m4a", log=lambda *_a: None)

    def test_skip_is_honoured(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "d.m4a")
            Path(src).write_bytes(b"fake")
            result = brief.analyze(
                os.path.join(tmp, "p"), src, skip=("normalize",),
                dry_run=True, log=lambda *_a: None,
            )
        self.assertIn("normalize", result["skipped"])


class WhisperVariantTests(unittest.TestCase):
    """An audio model already on the machine should be used as-is."""

    def test_openai_variant_argv(self):
        argv = local_tools.lyrics_command(
            "v.wav", "out", model="small", binary="whisper", kind="openai"
        )
        self.assertIn("--output_format", argv)
        self.assertEqual(argv[0], "whisper")

    def test_mlx_variant_argv(self):
        # mlx_whisper rejects openai-whisper's underscore flags.
        argv = local_tools.lyrics_command(
            "v.wav", "out", binary="mlx_whisper", kind="mlx"
        )
        self.assertEqual(argv[0], "mlx_whisper")
        self.assertIn("--output-dir", argv)
        self.assertNotIn("--output_dir", argv)

    def test_cpp_variant_uses_its_own_flags(self):
        argv = local_tools.lyrics_command(
            "v.wav", "out", binary="whisper-cli", kind="cpp", language="en"
        )
        self.assertIn("-f", argv)
        self.assertIn("-otxt", argv)
        self.assertIn("-l", argv)
        self.assertNotIn("--output_format", argv)

    def test_every_variant_has_an_install_hint(self):
        for binary, kind, install in local_tools.WHISPER_VARIANTS:
            self.assertTrue(binary and kind and install)

    def test_find_whisper_returns_none_or_a_triple(self):
        found = local_tools.find_whisper()
        self.assertTrue(found is None or len(found) == 3)


class TranscriptReadingTests(unittest.TestCase):
    def test_prefers_plain_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            txt = Path(tmp, "a.txt")
            txt.write_text("the words", encoding="utf-8")
            self.assertEqual(local_tools.read_transcript([str(txt)]), "the words")

    def test_falls_back_to_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            js = Path(tmp, "a.json")
            js.write_text('{"text": "from json"}', encoding="utf-8")
            self.assertEqual(local_tools.read_transcript([str(js)]), "from json")

    def test_empty_when_nothing_readable(self):
        self.assertEqual(local_tools.read_transcript([]), "")


if __name__ == "__main__":
    unittest.main()
