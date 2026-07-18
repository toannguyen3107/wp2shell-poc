# Target List CLI Design

## Goal

Add `-l FILE` / `--list FILE` support to the `check`, `read`, and `shell`
commands. Each non-empty line in the file is treated as one target URL. Existing
single-target command lines remain supported.

## Command-Line Interface

Every subcommand accepts exactly one target source:

```text
wp2shell check URL
wp2shell check -l targets.txt

wp2shell read URL [options]
wp2shell read -l targets.txt [options]

wp2shell shell URL [options]
wp2shell shell -l targets.txt [options]
```

The positional `URL` and `-l FILE` / `--list FILE` are mutually exclusive. The
argument parser reports an error when neither or both are provided.

All existing command-specific options keep their current meaning. In list mode,
the same options apply to every target. In particular, `shell` uses the same
credentials, command, interactive setting, and retention setting for every
target.

## Target File Handling

The target file is read as UTF-8 text. Each line is stripped of leading and
trailing whitespace, and empty lines are ignored. Remaining lines are processed
in file order without deduplication.

The command fails before processing any target if the file cannot be opened,
cannot be decoded as UTF-8, or contains no non-empty target lines. The error is
shown through the CLI's existing clean error-reporting path.

## Execution Model

Target-source expansion is centralized in the CLI dispatch layer rather than
duplicated in each command. The dispatcher produces either the single
positional URL or the URLs loaded from the file. For each URL, it creates a
per-target argument namespace with `url` set, then invokes the selected existing
command handler.

List mode prints a visible target header before each invocation so interleaved
results can be attributed to the correct URL. Single-target output remains
unchanged.

Per-target exceptions are caught in list mode, reported with the affected
target, and do not stop later targets. `KeyboardInterrupt` remains an immediate
abort and returns exit code 130.

## Exit Status

Single-target mode preserves each command's existing return code.

List mode processes every target and returns the greatest non-zero handler
return code observed. A caught per-target exception contributes exit code 1. If
every target returns 0, the overall return code is 0. This preserves meaningful
codes such as `check` returning 2 while satisfying the requirement that any
failed target makes the overall result non-zero.

## Testing

Automated CLI tests will cover:

- accepting a positional URL for each command;
- accepting `-l` and `--list` for each command;
- rejecting missing target input and simultaneous URL plus list input;
- stripping whitespace, ignoring blank lines, retaining order, and retaining
  duplicate target lines;
- rejecting unreadable, invalid UTF-8, and effectively empty list files;
- invoking the selected handler once per target with the correct URL;
- continuing after a non-zero result or exception;
- returning the greatest handler exit code;
- leaving single-target output and return behavior unchanged.

The README usage examples and options table will document list mode for all
three commands.
