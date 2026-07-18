import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wp2shell import cli


class TargetSourceTests(unittest.TestCase):
    def test_each_command_accepts_list_file_instead_of_url(self):
        parser = cli.build_parser()
        cases = (
            ["check", "-l", "targets.txt"],
            ["read", "--list", "targets.txt"],
            [
                "shell",
                "-l",
                "targets.txt",
                "--user",
                "admin",
                "--password",
                "password",
                "--cmd",
                "id",
            ],
        )

        for argv in cases:
            with self.subTest(argv=argv):
                args = parser.parse_args(argv)
                self.assertIsNone(args.url)
                self.assertEqual(args.target_file, "targets.txt")

    def test_each_command_still_accepts_positional_url(self):
        parser = cli.build_parser()
        cases = (
            ["check", "http://target"],
            ["read", "http://target"],
            [
                "shell",
                "http://target",
                "--user",
                "admin",
                "--password",
                "password",
                "--cmd",
                "id",
            ],
        )

        for argv in cases:
            with self.subTest(argv=argv):
                args = parser.parse_args(argv)
                self.assertEqual(args.url, "http://target")
                self.assertIsNone(args.target_file)

    def test_target_url_and_list_file_are_mutually_exclusive(self):
        parser = cli.build_parser()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["check", "http://target", "-l", "targets.txt"])

    def test_a_target_source_is_required(self):
        parser = cli.build_parser()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["check"])

    def test_load_targets_strips_blanks_and_preserves_order_and_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.txt"
            path.write_text(
                "  http://one  \n\nhttp://two\nhttp://one\n",
                encoding="utf-8",
            )

            targets = cli._load_targets(str(path))

        self.assertEqual(targets, ["http://one", "http://two", "http://one"])

    def test_load_targets_rejects_an_empty_list(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.txt"
            path.write_text(" \n\t\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "no targets"):
                cli._load_targets(str(path))

    def test_load_targets_surfaces_invalid_utf8(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.txt"
            path.write_bytes(b"\xff")

            with self.assertRaises(UnicodeDecodeError):
                cli._load_targets(str(path))


class ShellCommandTests(unittest.TestCase):
    def test_cleanup_runs_when_command_execution_raises(self):
        class FakeSession:
            instance = None

            def __init__(self, *args, **kwargs):
                self.cleaned = False
                type(self).instance = self

            def login(self, username, password):
                return True

            def deploy_webshell(self):
                return "/wp-content/plugins/wp2shell_test/wp2shell_test.php"

            def run(self, path, command):
                raise OSError("connection dropped")

            def cleanup(self, path):
                self.cleaned = True
                return True

        with mock.patch.object(cli, "AdminSession", FakeSession):
            rc = cli.main(
                [
                    "shell",
                    "http://target",
                    "--user",
                    "admin",
                    "--password",
                    "password",
                    "--cmd",
                    "id",
                    "--cleanup",
                ]
            )

        self.assertEqual(rc, 1)
        self.assertTrue(FakeSession.instance.cleaned)

    def test_keep_and_cleanup_are_mutually_exclusive(self):
        parser = cli.build_parser()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "shell",
                    "http://target",
                    "--user",
                    "admin",
                    "--password",
                    "password",
                    "--cmd",
                    "id",
                    "--keep",
                    "--cleanup",
                ]
            )

    def test_rest_route_is_not_a_shell_option(self):
        parser = cli.build_parser()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "shell",
                    "http://target",
                    "--user",
                    "admin",
                    "--password",
                    "password",
                    "--cmd",
                    "id",
                    "--rest-route",
                ]
            )


if __name__ == "__main__":
    unittest.main()
