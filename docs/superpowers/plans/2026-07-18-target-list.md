# Target List CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `check`, `read`, and `shell` process either one positional target URL or an ordered UTF-8 file containing one target per non-empty line.

**Architecture:** Keep the existing per-target command handlers unchanged. Add target-source parsing and expansion to the shared CLI layer, then dispatch a copied argument namespace to the selected handler for each target while aggregating return codes and isolating per-target exceptions.

**Tech Stack:** Python 3.8+, standard-library `argparse`, `copy`, and `pathlib`; standard-library `unittest`.

## Global Constraints

- Python 3.8+ and standard library only; add no third-party dependencies.
- `URL` and `-l FILE` / `--list FILE` are mutually exclusive and exactly one is required.
- Read target files as UTF-8, strip surrounding whitespace, ignore blank lines, preserve order, and preserve duplicates.
- Apply the same command options to every target in list mode.
- Continue after a target returns non-zero or raises an ordinary exception.
- Return the greatest handler exit code; a caught exception contributes exit code 1.
- Let `KeyboardInterrupt` abort immediately with exit code 130.
- Keep single-target output and return behavior unchanged.

---

## File Structure

- Modify `wp2shell/cli.py`: parse the target source, load list files, and dispatch targets.
- Modify `tests/test_cli.py`: cover parser behavior, file normalization/errors, dispatch continuation, and exit-code aggregation.
- Modify `README.md`: document `-l FILE` for all commands.

### Task 1: Target source parsing and file loading

**Files:**
- Modify: `wp2shell/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `argparse.ArgumentParser` subparsers created by `build_parser()`.
- Produces: `_load_targets(path: str) -> list[str]`; every parsed command namespace has `url: Optional[str]` and `target_file: Optional[str]`.

- [ ] **Step 1: Write failing parser and loader tests**

Add these imports and test class to `tests/test_cli.py`:

```python
import tempfile
from pathlib import Path


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
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_cli.TargetSourceTests -v
```

Expected: failures because `-l` is unrecognized, `url` is still required, and `cli._load_targets` does not exist.

- [ ] **Step 3: Implement mutually exclusive target parsing and UTF-8 loading**

Add the import to `wp2shell/cli.py`:

```python
from pathlib import Path
```

Add this helper before the command handlers:

```python
def _load_targets(path: str) -> list[str]:
    targets = [
        line.strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not targets:
        raise ValueError(f"target list contains no targets: {path}")
    return targets
```

Replace the positional URL declaration in `_add_common()` with:

```python
    targets = parser.add_mutually_exclusive_group(required=True)
    targets.add_argument("url", nargs="?", help="target base URL, e.g. http://target")
    targets.add_argument(
        "-l",
        "--list",
        dest="target_file",
        metavar="FILE",
        help="read target URLs from FILE, one per non-empty line",
    )
```

- [ ] **Step 4: Run focused and full tests and verify GREEN**

Run:

```powershell
python -m unittest tests.test_cli.TargetSourceTests -v
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the parser and loader**

```powershell
git add wp2shell/cli.py tests/test_cli.py
git commit -m "feat: accept target list files"
```

### Task 2: Multi-target dispatch and failure isolation

**Files:**
- Modify: `wp2shell/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `_load_targets(path: str) -> list[str]` and parsed `args.func`.
- Produces: `_dispatch(args: argparse.Namespace) -> int`, which preserves single-target behavior and aggregates list-mode outcomes.

- [ ] **Step 1: Write failing dispatch tests**

Add this test class to `tests/test_cli.py`:

```python
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
```

Also add `import argparse` to `tests/test_cli.py`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_cli.TargetDispatchTests -v
```

Expected: errors because `cli._dispatch` does not exist.

- [ ] **Step 3: Implement target dispatch**

Add this import to `wp2shell/cli.py`:

```python
import copy
```

Add this helper above `main()`:

```python
def _dispatch(args: argparse.Namespace) -> int:
    if args.target_file is None:
        return args.func(args)

    result = 0
    for target in _load_targets(args.target_file):
        info(f"Target: {target}")
        target_args = copy.copy(args)
        target_args.url = target
        try:
            target_result = target_args.func(target_args)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 - isolate failures between targets
            bad(f"{target}: {exc}")
            target_result = 1
        result = max(result, target_result)
    return result
```

Change the successful dispatch line in `main()`:

```python
        return _dispatch(args)
```

- [ ] **Step 4: Run focused and full tests and verify GREEN**

Run:

```powershell
python -m unittest tests.test_cli.TargetDispatchTests -v
python -m unittest discover -s tests -v
```

Expected: all tests pass with no warnings or tracebacks.

- [ ] **Step 5: Commit dispatch behavior**

```powershell
git add wp2shell/cli.py tests/test_cli.py
git commit -m "feat: run commands across target lists"
```

### Task 3: User documentation and final verification

**Files:**
- Modify: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: the completed `URL` or `-l FILE` CLI and list-mode semantics.
- Produces: documented usage examples and options matching the implementation.

- [ ] **Step 1: Add a failing documentation assertion**

Add this test to `TargetSourceTests` in `tests/test_cli.py`:

```python
    def test_list_option_is_visible_in_help(self):
        help_text = cli.build_parser().format_help()
        for command in ("check", "read", "shell"):
            subparser = cli.build_parser()._subparsers._group_actions[0].choices[command]
            self.assertIn("-l FILE", subparser.format_help())
            self.assertIn("--list FILE", subparser.format_help())
```

- [ ] **Step 2: Run the focused test and verify its baseline**

Run:

```powershell
python -m unittest tests.test_cli.TargetSourceTests.test_list_option_is_visible_in_help -v
```

Expected: PASS because Tasks 1 and 2 exposed the option. This test is a regression assertion for the user-facing help rather than a new production behavior; the RED cycle for the option itself was completed in Task 1.

- [ ] **Step 3: Update README usage and options**

Change the general usage block to:

```text
./wp2shell.py <command> <url> [options]
./wp2shell.py <command> -l targets.txt [options]
```

Add one list-mode example after the three command sections:

```markdown
### Multiple targets

All commands accept `-l FILE` / `--list FILE` instead of a positional URL. The
file must be UTF-8 with one target URL per line; blank lines are ignored.
Targets run in file order, and a failure on one target does not stop the rest.
The same command options apply to every target.

```text
./wp2shell.py check -l targets.txt
./wp2shell.py read -l targets.txt --preset users
./wp2shell.py shell -l targets.txt --user admin --password '<recovered>' --cmd id --cleanup
```
```

Add this row to the options table:

```markdown
| `-l FILE` / `--list FILE` | all | Read target URLs from a UTF-8 file, one per non-empty line. |
```

- [ ] **Step 4: Run final verification**

Run:

```powershell
python -m unittest discover -s tests -v
python wp2shell.py check --help
python wp2shell.py read --help
python wp2shell.py shell --help
git diff --check
```

Expected: all tests pass; each help command shows mutually exclusive `URL` and
`-l FILE`; `git diff --check` prints no errors.

- [ ] **Step 5: Commit documentation**

```powershell
git add README.md tests/test_cli.py
git commit -m "docs: describe multi-target usage"
```
