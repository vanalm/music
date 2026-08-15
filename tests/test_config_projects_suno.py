"""Config, project scaffolding, Suno fail-closed behaviour, and the CLI wiring."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from music_stack import cli, projects
from music_stack.adapters import suno
from music_stack.config import Settings, fingerprint, parse_env
from music_stack.errors import MusicStackError, NotConfiguredError


class EnvParsingTests(unittest.TestCase):
    def test_parses_quotes_comments_and_export(self):
        parsed = parse_env(
            "\n".join(
                [
                    "# a comment",
                    "",
                    "PLAIN=value",
                    'QUOTED="with spaces"',
                    "SINGLE='single'",
                    "export EXPORTED=exported",
                    "  SPACED = padded  ",
                    "NOT_A_PAIR",
                ]
            )
        )
        self.assertEqual(parsed["PLAIN"], "value")
        self.assertEqual(parsed["QUOTED"], "with spaces")
        self.assertEqual(parsed["SINGLE"], "single")
        self.assertEqual(parsed["EXPORTED"], "exported")
        self.assertEqual(parsed["SPACED"], "padded")
        self.assertNotIn("NOT_A_PAIR", parsed)

    def test_real_environment_wins_over_dotenv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("")
            (root / ".env").write_text("MUSIC_AI_API_KEY=from-file\n")
            settings = Settings(environ={"MUSIC_AI_API_KEY": "from-shell"}, root=root)
            self.assertEqual(settings.get("MUSIC_AI_API_KEY"), "from-shell")

    def test_dotenv_used_when_shell_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("KITS_API_KEY=from-file\n")
            settings = Settings(environ={}, root=root)
            self.assertEqual(settings.get("KITS_API_KEY"), "from-file")


class SecretHandlingTests(unittest.TestCase):
    def test_describe_reports_presence_never_value(self):
        secret = "sk-super-secret-value"
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(environ={"MUSIC_AI_API_KEY": secret}, root=tmp)
            rows = settings.describe()
            rendered = json.dumps(rows)
            self.assertNotIn(secret, rendered)
            music_row = [r for r in rows if r[1] == "MUSIC_AI_API_KEY"][0]
            self.assertTrue(music_row[2])  # configured

    def test_fingerprint_is_stable_short_and_not_the_secret(self):
        secret = "sk-super-secret-value"
        fp = fingerprint(secret)
        self.assertEqual(fp, fingerprint(secret))
        self.assertEqual(len(fp), 8)
        self.assertNotIn(fp, secret)
        self.assertNotEqual(fingerprint("other"), fp)

    def test_fingerprint_of_missing_is_placeholder(self):
        self.assertEqual(fingerprint(None), "—")
        self.assertEqual(fingerprint(""), "—")

    def test_require_missing_key_explains_how_to_set_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(environ={}, root=tmp)
            with self.assertRaises(NotConfiguredError) as ctx:
                settings.require("MUSIC_AI_API_KEY", service="Music.AI")
            self.assertIn(".env", str(ctx.exception))

    def test_doctor_output_contains_no_secret(self):
        import io
        from contextlib import redirect_stdout

        secret = "sk-do-not-print-me"
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                environ={"MUSIC_AI_API_KEY": secret, "KITS_API_KEY": secret}, root=tmp
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli.cmd_doctor(None, settings)
            output = buf.getvalue()
        self.assertNotIn(secret, output)
        self.assertIn("configured", output)


class SunoFailClosedTests(unittest.TestCase):
    def test_unconfigured_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = suno.status(Settings(environ={}, root=tmp))
        self.assertEqual(state["status"], "unconfigured")
        self.assertIn("SUNO_API_KEY", state["missing"])
        self.assertIn("SUNO_API_BASE", state["missing"])

    def test_key_alone_is_not_enough(self):
        """A key without a documented base URL would mean guessing endpoints."""
        with tempfile.TemporaryDirectory() as tmp:
            state = suno.status(Settings(environ={"SUNO_API_KEY": "k"}, root=tmp))
        self.assertEqual(state["status"], "unconfigured")
        self.assertEqual(state["missing"], ["SUNO_API_BASE"])

    def test_client_refuses_to_construct_when_unconfigured(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(NotConfiguredError):
                suno.SunoClient(Settings(environ={}, root=tmp))

    def test_configured_client_still_refuses_invented_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = suno.SunoClient(
                Settings(
                    environ={"SUNO_API_KEY": "k", "SUNO_API_BASE": "https://x/v1"},
                    root=tmp,
                )
            )
            with self.assertRaises(NotConfiguredError) as ctx:
                client.generate_song()
            self.assertIn("unofficial", str(ctx.exception))


class ProjectTests(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(projects.slugify("Working Title"), "working-title")
        self.assertEqual(projects.slugify("Don't Look Back!"), "don-t-look-back")
        self.assertEqual(projects.slugify("  Café Song  "), "cafe-song")
        self.assertEqual(projects.slugify("A -- B"), "a-b")

    def test_slugify_rejects_empty_result(self):
        with self.assertRaises(MusicStackError):
            projects.slugify("!!!")

    def test_create_builds_full_tree_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = projects.create(tmp, "Working Title")
            for sub in projects.SUBDIRS:
                self.assertTrue((path / sub).is_dir(), sub)
            meta = projects.load(path)
            self.assertEqual(meta["title"], "Working Title")
            self.assertEqual(meta["slug"], "working-title")
            self.assertEqual(meta["jobs"], [])

    def test_create_refuses_to_clobber_without_exist_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects.create(tmp, "Song")
            with self.assertRaises(MusicStackError):
                projects.create(tmp, "Song")
            # exist_ok fills gaps instead of failing
            path = projects.create(tmp, "Song", exist_ok=True)
            self.assertTrue(path.exists())

    def test_create_preserves_metadata_on_exist_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = projects.create(tmp, "Song")
            projects.record_job(path, {"service": "kits", "job_id": "1"})
            projects.create(tmp, "Song", exist_ok=True)
            self.assertEqual(len(projects.load(path)["jobs"]), 1)

    def test_record_job_appends_audit_trail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = projects.create(tmp, "Song")
            projects.record_job(path, {"service": "music-ai", "job_id": "a"})
            projects.record_job(path, {"service": "kits", "job_id": "b"})
            jobs = projects.load(path)["jobs"]
            self.assertEqual([j["job_id"] for j in jobs], ["a", "b"])

    def test_listing_ignores_non_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects.create(tmp, "One")
            os.makedirs(os.path.join(tmp, "not-a-project"))
            self.assertEqual(projects.listing(tmp), ["one"])

    def test_listing_missing_root_is_empty(self):
        self.assertEqual(projects.listing("/nope/does/not/exist"), [])


class CliWiringTests(unittest.TestCase):
    def test_parser_builds_and_every_command_has_a_handler(self):
        parser = cli.build_parser()
        for argv in (
            ["doctor"],
            ["project", "new", "Song"],
            ["project", "list"],
            ["audio", "normalize", "a.m4a", "b.wav"],
            ["audio", "inspect", "a.wav"],
            ["music-ai", "workflows"],
            ["music-ai", "process", "--workflow", "w", "--input", "i", "--output", "o"],
            ["kits", "models"],
            ["kits", "vocals", "--input", "i", "--output", "o"],
            ["kits", "convert", "--input", "i", "--output", "o", "--voice-model", "1"],
            ["suno", "status"],
        ):
            args = parser.parse_args(argv)
            self.assertTrue(callable(args.func), argv)

    def test_missing_credential_exits_2_not_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                Path(tmp, "pyproject.toml").write_text("")
                for var in ("MUSIC_AI_API_KEY", "KITS_API_KEY"):
                    os.environ.pop(var, None)
                code = cli.main(["kits", "models"])
            finally:
                os.chdir(cwd)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
