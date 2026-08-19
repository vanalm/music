"""Local analysis tool tests.

Demucs, allin1, and Whisper are not installed in CI, so the tests here focus on
the two things that are verifiable without them: the argv each command builds
(so a flag change is caught by a diff, not by a failed run at 1am), and that a
missing tool fails with an install hint rather than a traceback.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from music_stack import local_tools
from music_stack.errors import AudioError, MusicStackError


def wav(tmp, name="song.wav"):
    path = os.path.join(tmp, name)
    Path(path).write_bytes(b"RIFFfake")
    return path


class ToolDetectionTests(unittest.TestCase):
    def test_missing_tool_names_the_install_command(self):
        tool = local_tools.TOOLS["demucs"]
        if tool.which():  # pragma: no cover - only when demucs is installed
            self.skipTest("demucs is installed here")
        with self.assertRaises(MusicStackError) as ctx:
            tool.require()
        message = str(ctx.exception)
        self.assertIn("pip install -U demucs", message)
        self.assertIn("github.com", message)

    def test_allin1_hint_warns_about_madmom(self):
        # The single most common install failure for allin1.
        self.assertIn("madmom", local_tools.TOOLS["allin1"].install)
        self.assertIn("git", local_tools.TOOLS["allin1"].note.lower() + local_tools.TOOLS["allin1"].install)

    def test_status_reports_every_tool(self):
        rows = local_tools.status()
        self.assertEqual(len(rows), len(local_tools.TOOLS))
        for key, binary, _found, install in rows:
            self.assertTrue(install, key)
            self.assertTrue(binary, key)

    def test_device_detection_is_platform_aware(self):
        device = local_tools.detect_device()
        self.assertIn(device, ("mps", None))


class CommandBuildingTests(unittest.TestCase):
    """The argv is the contract with each external tool -- pin it."""

    def test_demucs_default_command(self):
        argv = local_tools.stems_command("in.wav", "out/")
        self.assertEqual(
            argv,
            ["demucs", "-n", "htdemucs", "-o", "out/", "in.wav"],
        )

    def test_demucs_with_device_and_two_stems(self):
        argv = local_tools.stems_command(
            "in.wav", "out/", model="htdemucs_ft", device="mps", two_stems="vocals"
        )
        self.assertEqual(
            argv,
            [
                "demucs", "-n", "htdemucs_ft", "-o", "out/",
                "--device", "mps", "--two-stems", "vocals", "in.wav",
            ],
        )

    def test_input_is_always_last(self):
        # Demucs treats trailing positionals as tracks; a flag after the input
        # would be parsed as another track.
        argv = local_tools.stems_command("in.wav", "out/", device="mps")
        self.assertEqual(argv[-1], "in.wav")

    def test_allin1_passes_overwrite_and_a_resolved_path(self):
        # --overwrite: without it a re-analysis crashes on allin1's own
        # cached demix instead of replacing it.
        argv = local_tools.structure_command("in.wav")
        self.assertEqual(argv[:2], ["allin1", "--overwrite"])
        self.assertEqual(len(argv), 3)
        self.assertTrue(os.path.isabs(argv[-1]))

    def test_whisper_command(self):
        argv = local_tools.lyrics_command("v.wav", "out/", model="medium", language="en")
        self.assertEqual(
            argv,
            [
                "whisper", "v.wav", "--model", "medium",
                "--output_dir", "out/", "--output_format", "all",
                "--language", "en",
            ],
        )

    def test_whisper_omits_language_when_unset(self):
        argv = local_tools.lyrics_command("v.wav", "out/")
        self.assertNotIn("--language", argv)

    def test_mlx_whisper_command_uses_dashed_flags_and_hub_repo(self):
        # mlx_whisper rejects the openai-whisper underscore flags, and its
        # --model resolves against the Hub, where "small" is not a repo.
        argv = local_tools.lyrics_command(
            "v.wav", "out/", model="small", language="en",
            binary="mlx_whisper", kind="mlx",
        )
        self.assertEqual(
            argv,
            [
                "mlx_whisper", "v.wav",
                "--model", "mlx-community/whisper-small-mlx",
                "--output-dir", "out/", "--output-format", "all",
                "--language", "en",
            ],
        )

    def test_mlx_whisper_passes_explicit_repo_and_local_dir_through(self):
        argv = local_tools.lyrics_command(
            "v.wav", "out/", model="mlx-community/whisper-turbo",
            binary="mlx_whisper", kind="mlx",
        )
        self.assertIn("mlx-community/whisper-turbo", argv)
        with tempfile.TemporaryDirectory() as tmp:
            argv = local_tools.lyrics_command(
                "v.wav", "out/", model=tmp, binary="mlx_whisper", kind="mlx",
            )
            self.assertIn(tmp, argv)


class DryRunTests(unittest.TestCase):
    """--dry-run must work with the tool absent; that is its whole purpose."""

    def test_stems_dry_run_needs_no_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = local_tools.stems(wav(tmp), tmp, dry_run=True)
            self.assertEqual(result["command"][0], "demucs")
            self.assertNotIn("files", result)

    def test_structure_dry_run_reports_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = local_tools.structure(wav(tmp), tmp, dry_run=True)
            self.assertEqual(result["cwd"], tmp)

    def test_lyrics_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = local_tools.lyrics(wav(tmp), tmp, dry_run=True)
            # Whichever variant this machine has, some output flag is present.
            self.assertTrue(
                {"--output_format", "--output-format", "-otxt"}
                & set(result["command"])
            )

    def test_dry_run_still_validates_the_input_exists(self):
        with self.assertRaises(AudioError):
            local_tools.stems("/nope/missing.wav", "/tmp/out", dry_run=True)


class StructureSummaryTests(unittest.TestCase):
    SAMPLE = {
        "path": "song.wav",
        "bpm": 92,
        "beats": [0.5, 1.0, 1.5, 2.0],
        "downbeats": [0.5, 2.5],
        "segments": [
            {"start": 0.0, "end": 8.0, "label": "intro"},
            {"start": 8.0, "end": 32.0, "label": "verse"},
            {"start": 32.0, "end": 56.0, "label": "chorus"},
            {"start": 56.0, "end": 80.0, "label": "verse"},
        ],
    }

    def _summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "song.json")
            Path(path).write_text(json.dumps(self.SAMPLE), encoding="utf-8")
            return local_tools.summarize_structure(path)

    def test_reports_tempo_and_counts(self):
        s = self._summary()
        self.assertEqual(s["bpm"], 92)
        self.assertEqual(s["beats"], 4)
        self.assertEqual(s["downbeats"], 2)
        self.assertEqual(s["section_count"], 4)
        self.assertEqual(s["duration_seconds"], 80.0)

    def test_renders_the_arrangement(self):
        self.assertEqual(
            self._summary()["arrangement"], "intro → verse → chorus → verse"
        )

    def test_flags_what_the_song_is_missing(self):
        """The point of the summary: what is not there yet."""
        self.assertEqual(self._summary()["missing"], ["bridge", "outro"])

    def test_section_durations_are_computed(self):
        sections = self._summary()["sections"]
        self.assertEqual(sections[0]["seconds"], 8.0)
        self.assertEqual(sections[1]["seconds"], 24.0)

    def test_handles_empty_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.json")
            Path(path).write_text(json.dumps({"bpm": 120}), encoding="utf-8")
            summary = local_tools.summarize_structure(path)
            self.assertIsNone(summary["duration_seconds"])
            self.assertIsNone(summary["arrangement"])
            self.assertEqual(summary["section_count"], 0)


if __name__ == "__main__":
    unittest.main()
