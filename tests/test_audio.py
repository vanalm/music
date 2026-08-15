"""Audio tests.

The conversion tests need a real ffmpeg and are skipped when it is absent, so
the suite stays green on a machine that has not bootstrapped yet (CI, or a
fresh checkout). The guard-rail tests below run everywhere — they are the ones
that assert a *missing* ffmpeg fails helpfully rather than with a traceback.
"""

import os
import pathlib
import subprocess
import tempfile
import unittest

from music_stack import audio
from music_stack.errors import AudioError

HAS_FFMPEG = bool(audio.which("ffmpeg") and audio.which("ffprobe"))
requires_ffmpeg = unittest.skipUnless(
    HAS_FFMPEG, "ffmpeg/ffprobe not installed; run ./scripts/bootstrap-macos.sh"
)


class MissingBinaryTests(unittest.TestCase):
    """These are the tests that matter on an un-bootstrapped machine."""

    def test_require_names_the_install_command(self):
        with self.assertRaises(AudioError) as ctx:
            audio.require("definitely-not-a-real-binary")
        message = str(ctx.exception)
        self.assertIn("brew install ffmpeg", message)
        self.assertIn("bootstrap-macos.sh", message)

    def test_inspect_missing_file_is_clear(self):
        with self.assertRaises(AudioError) as ctx:
            audio.inspect("/nope/missing.wav")
        self.assertIn("No such audio file", str(ctx.exception))

    def test_normalize_missing_source_is_clear(self):
        with self.assertRaises(AudioError) as ctx:
            audio.normalize("/nope/missing.m4a", "/tmp/out.wav")
        self.assertIn("No such audio file", str(ctx.exception))

    def test_rejects_unsupported_bit_depth(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "in.wav")
            pathlib.Path(src).write_bytes(b"RIFF")
            with self.assertRaises(AudioError) as ctx:
                audio.normalize(src, os.path.join(tmp, "o.wav"), bit_depth=17)
            self.assertIn("Unsupported bit depth", str(ctx.exception))

    def test_refuses_to_overwrite_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dest = os.path.join(tmp, "in.wav"), os.path.join(tmp, "out.wav")
            pathlib.Path(src).write_bytes(b"RIFF")
            pathlib.Path(dest).write_bytes(b"existing")
            with self.assertRaises(AudioError) as ctx:
                audio.normalize(src, dest)
            self.assertIn("--overwrite", str(ctx.exception))
            # and the existing file is untouched
            self.assertEqual(pathlib.Path(dest).read_bytes(), b"existing")


@requires_ffmpeg
class ConversionTests(unittest.TestCase):
    """Real ffmpeg round trips, skipped when ffmpeg is unavailable."""

    def _tone(self, path, *, rate=8000, bits=16, seconds=1):
        codec = {16: "pcm_s16le", 24: "pcm_s24le"}[bits]
        subprocess.run(
            [
                audio.require("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "sine=frequency=440:duration={}".format(seconds),
                "-ar", str(rate), "-acodec", codec, path,
            ],
            check=True,
        )
        return path

    def test_upsamples_8k_16bit_to_48k_24bit(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self._tone(os.path.join(tmp, "in.wav"))
            dest = audio.normalize(src, os.path.join(tmp, "out.wav"))
            summary = audio.inspect(dest)["summary"]
            self.assertEqual(summary["sample_rate"], 48000)
            self.assertEqual(summary["bit_depth"], 24)
            self.assertAlmostEqual(summary["duration_seconds"], 1.0, places=1)

    def test_inspect_summary_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self._tone(os.path.join(tmp, "in.wav"))
            summary = audio.inspect(src)["summary"]
            for field in ("codec", "sample_rate", "channels", "duration_seconds", "size_bytes"):
                self.assertIsNotNone(summary[field], field)

    def test_overwrite_flag_replaces_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self._tone(os.path.join(tmp, "in.wav"))
            dest = os.path.join(tmp, "out.wav")
            audio.normalize(src, dest)
            first = os.path.getsize(dest)
            audio.normalize(src, dest, overwrite=True)
            self.assertEqual(os.path.getsize(dest), first)

    def test_creates_missing_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self._tone(os.path.join(tmp, "in.wav"))
            dest = os.path.join(tmp, "a", "b", "c", "out.wav")
            audio.normalize(src, dest)
            self.assertTrue(os.path.exists(dest))

    def test_corrupt_input_reports_ffmpeg_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.wav")
            pathlib.Path(bad).write_bytes(b"not actually audio at all")
            with self.assertRaises(AudioError) as ctx:
                audio.normalize(bad, os.path.join(tmp, "out.wav"))
            self.assertIn("ffmpeg exited", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
