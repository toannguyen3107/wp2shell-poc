import argparse
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

    def test_main_reports_a_missing_target_file_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.txt"
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                result = cli.main(["check", "-l", str(path)])

        self.assertEqual(result, 1)
        self.assertIn("No such file or directory", output.getvalue())
        self.assertIn("missing.txt", output.getvalue())

    def test_list_option_is_visible_in_help(self):
        parser = cli.build_parser()
        subparsers = parser._subparsers._group_actions[0].choices

        for command in ("check", "read", "shell"):
            with self.subTest(command=command):
                help_text = subparsers[command].format_help()
                self.assertIn("-l FILE", help_text)
                self.assertIn("--list FILE", help_text)


class TargetDispatchTests(unittest.TestCase):
    def test_single_target_calls_handler_without_target_header(self):
        handler = mock.Mock(return_value=2)
        args = argparse.Namespace(
            url="http://one",
            target_file=None,
            func=handler,
        )
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            result = cli._dispatch(args)

        self.assertEqual(result, 2)
        handler.assert_called_once_with(args)
        self.assertEqual(output.getvalue(), "")

    def test_list_mode_runs_all_targets_and_returns_greatest_code(self):
        handler = mock.Mock(side_effect=[0, 2, 1])
        args = argparse.Namespace(
            url=None,
            target_file="targets.txt",
            func=handler,
        )

        with mock.patch.object(
            cli,
            "_load_targets",
            return_value=["http://one", "http://two", "http://three"],
        ), contextlib.redirect_stdout(io.StringIO()):
            result = cli._dispatch(args)

        self.assertEqual(result, 2)
        self.assertEqual(
            [call.args[0].url for call in handler.call_args_list],
            ["http://one", "http://two", "http://three"],
        )
        self.assertTrue(all(call.args[0] is not args for call in handler.call_args_list))

    def test_list_mode_continues_after_exception_and_names_target(self):
        handler = mock.Mock(side_effect=[OSError("offline"), 0])
        args = argparse.Namespace(
            url=None,
            target_file="targets.txt",
            func=handler,
        )
        output = io.StringIO()

        with mock.patch.object(
            cli,
            "_load_targets",
            return_value=["http://bad", "http://good"],
        ), contextlib.redirect_stdout(output):
            result = cli._dispatch(args)

        self.assertEqual(result, 1)
        self.assertEqual(handler.call_count, 2)
        self.assertIn("http://bad: offline", output.getvalue())

    def test_list_mode_does_not_swallow_keyboard_interrupt(self):
        handler = mock.Mock(side_effect=KeyboardInterrupt)
        args = argparse.Namespace(
            url=None,
            target_file="targets.txt",
            func=handler,
        )

        with mock.patch.object(
            cli,
            "_load_targets",
            return_value=["http://one"],
        ), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(KeyboardInterrupt):
            cli._dispatch(args)

    def test_interactive_shell_interrupt_aborts_the_whole_target_list(self):
        class FakeSession:
            instances = []

            def __init__(self, *args, **kwargs):
                type(self).instances.append(self)

            def login(self, username, password):
                return True

            def deploy_webshell(self):
                return "/wp-content/plugins/wp2shell_test/wp2shell_test.php"

            def run(self, path, command):
                return "/tmp\n"

            def cleanup(self, path):
                return True

        with tempfile.TemporaryDirectory() as directory:
            target_file = Path(directory) / "targets.txt"
            target_file.write_text("http://one\nhttp://two\n", encoding="utf-8")

            with (
                mock.patch.object(cli, "AdminSession", FakeSession),
                mock.patch("builtins.input", side_effect=KeyboardInterrupt),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = cli.main(
                    [
                        "shell",
                        "-l",
                        str(target_file),
                        "--user",
                        "admin",
                        "--password",
                        "password",
                        "--interactive",
                    ]
                )

        self.assertEqual(result, 130)
        self.assertEqual(len(FakeSession.instances), 1)


class ShellCommandTests(unittest.TestCase):
    def test_cleanup_runs_by_default_when_command_execution_raises(self):
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
                ]
            )

        self.assertEqual(rc, 1)
        self.assertTrue(FakeSession.instance.cleaned)

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
