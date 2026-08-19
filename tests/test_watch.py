"""Drop-folder watcher tests. The analyze step is injected, so these verify
the folder mechanics — selection, stability, filing — without ffmpeg."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from music_stack import watch

# No test may post a real macOS notification; anything that wants one
# injects its own notify_fn.
_real_notify = watch.notify
_quiet = mock.patch.object(watch, "notify", lambda *_a: None)


def setUpModule():
    _quiet.start()


def tearDownModule():
    _quiet.stop()


def drop(tmp, name, data=b"RIFFfake"):
    path = Path(tmp) / name
    path.write_bytes(data)
    return path


def fake_analyze(root, path, log=print):
    return {"slug": Path(path).stem, "brief_path": "/tmp/x/brief.md",
            "report_path": "/tmp/x/report.html"}


class ScanTests(unittest.TestCase):
    def test_finds_audio_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            drop(tmp, "memo.m4a")
            drop(tmp, "video.mov")
            drop(tmp, "notes.txt")
            drop(tmp, "cover.jpg")
            names = [p.name for p in watch.scan(tmp)]
        self.assertEqual(names, ["memo.m4a", "video.mov"])

    def test_skips_airdrop_temporaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            drop(tmp, ".memo.m4a")   # dotfile = mid-transfer
            self.assertEqual(watch.scan(tmp), [])

    def test_skips_done_and_failed_subfolders(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = Path(tmp) / watch.DONE_DIR
            done.mkdir()
            (done / "old.m4a").write_bytes(b"x")
            self.assertEqual(watch.scan(tmp), [])

    def test_missing_dir_is_empty_not_an_error(self):
        self.assertEqual(watch.scan("/nope/never"), [])


class StabilityTests(unittest.TestCase):
    def test_stable_file_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = drop(tmp, "a.m4a")
            self.assertTrue(watch.is_stable(path, sleep=lambda _s: None))

    def test_growing_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = drop(tmp, "a.m4a")

            def grow(_seconds):
                with open(path, "ab") as fh:
                    fh.write(b"more bytes arriving")

            self.assertFalse(watch.is_stable(path, sleep=grow))

    def test_empty_file_is_not_stable(self):
        # Zero bytes means the copy has not really begun.
        with tempfile.TemporaryDirectory() as tmp:
            path = drop(tmp, "a.m4a", data=b"")
            self.assertFalse(watch.is_stable(path, sleep=lambda _s: None))

    def test_vanished_file_is_not_stable(self):
        self.assertFalse(watch.is_stable("/nope/gone.m4a", sleep=lambda _s: None))


class ProcessTests(unittest.TestCase):
    def test_success_moves_original_to_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = drop(tmp, "memo.m4a")
            result = watch.process(path, tmp, analyze_fn=fake_analyze,
                                   log=lambda *_a: None)
            self.assertIsNotNone(result)
            self.assertFalse(path.exists())
            self.assertTrue((Path(tmp) / watch.DONE_DIR / "memo.m4a").exists())

    def test_failure_moves_to_failed_not_retried(self):
        def boom(root, path, log=print):
            raise RuntimeError("corrupt file")

        with tempfile.TemporaryDirectory() as tmp:
            path = drop(tmp, "bad.m4a")
            logs = []
            result = watch.process(path, tmp, analyze_fn=boom, log=logs.append)
            self.assertIsNone(result)
            self.assertTrue((Path(tmp) / watch.FAILED_DIR / "bad.m4a").exists())
            self.assertIn("corrupt file", " ".join(logs))
            # and the folder no longer offers it for processing
            self.assertEqual(watch.scan(tmp), [])

    def test_same_name_twice_never_clobbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            for _ in range(2):
                path = drop(tmp, "memo.m4a")
                watch.process(path, tmp, analyze_fn=fake_analyze,
                              log=lambda *_a: None)
            done = sorted(p.name for p in (Path(tmp) / watch.DONE_DIR).iterdir())
            self.assertEqual(done, ["memo-1.m4a", "memo.m4a"])

    def test_success_notifies_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = drop(tmp, "memo.m4a")
            seen = []
            watch.process(path, tmp, analyze_fn=fake_analyze,
                          log=lambda *_a: None,
                          notify_fn=lambda t, m: seen.append(m))
            self.assertTrue(any("done" in m for m in seen))

    def test_failure_notifies_too(self):
        def boom(root, path, log=print):
            raise RuntimeError("corrupt file")

        with tempfile.TemporaryDirectory() as tmp:
            path = drop(tmp, "bad.m4a")
            seen = []
            watch.process(path, tmp, analyze_fn=boom, log=lambda *_a: None,
                          notify_fn=lambda t, m: seen.append(m))
            self.assertTrue(any("FAILED" in m for m in seen))

    def test_notify_survives_a_missing_osascript(self):
        with mock.patch.object(watch.shutil, "which", return_value=None):
            self.assertIsNone(_real_notify("t", "m"))


class RunOnceTests(unittest.TestCase):
    def test_processes_everything_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            drop(tmp, "one.m4a")
            drop(tmp, "two.mp3")
            results = watch.run_once(
                tmp, tmp, analyze_fn=fake_analyze,
                log=lambda *_a: None, sleep=lambda _s: None,
            )
            self.assertEqual(len(results), 2)
            self.assertEqual(watch.scan(tmp), [])

    def test_unstable_file_is_left_for_next_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = drop(tmp, "copying.m4a")

            def grow(_seconds):
                with open(path, "ab") as fh:
                    fh.write(b"still arriving")

            logs = []
            results = watch.run_once(
                tmp, tmp, analyze_fn=fake_analyze, log=logs.append, sleep=grow
            )
            self.assertEqual(results, [])
            self.assertTrue(path.exists())
            self.assertIn("copying", " ".join(logs))


if __name__ == "__main__":
    unittest.main()
