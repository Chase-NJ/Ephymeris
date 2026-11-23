#!/usr/bin/env python3
"""PreToolUse hook on Bash: trim pytest and log output before it reaches the context.

As a hook (no arguments) it reads the tool call on stdin and either prints `{}` (run the
command unchanged) or rewrites it to pipe through this same file:

  --pytest  keep the FAILURES/ERRORS sections, the short summary and the final line
  --log     keep ERROR/WARN/Traceback lines with their line numbers, then the tail

Only a whole command that is a plain pytest run, or a plain cat/head/tail of a log-like
file, is rewritten (one leading `cd DIR &&` allowed). Anything with a pipe, `;`, `$`,
a redirect, a newline or unbalanced quotes passes through, as does a command ending in
`# raw`. A pytest rewrite is allowed without a prompt only when the original matches an
allow rule in settings.json; every other rewrite asks. Stdlib only.
"""

import json
import os
import re
import shlex
import sys

CAP = 100
ESCAPE = re.compile(r"#\s*raw\s*$")
UNSAFE = re.compile(r"[;&|<>`$(){}\\\n]")
CD_PREFIX = re.compile(r"^cd\s+([\w./~-]+)\s*&&\s*")

#: Executables whose pytest runs settings.json already allows (`Bash(<exe>:*)`).
ALLOWED_EXES = {"pytest", "python", "python3", ".venv/bin/python", "sidecar/.venv/bin/python"}
PYTHON = re.compile(r"^(?:\S*/)?python3?(?:\.\d+)?$")
#: pytest flags whose output is the point, or that wait for a human.
PYTEST_PASS = {"--pdb", "--trace", "--co", "--collect-only", "-h", "--help", "--version",
               "--fixtures", "--markers", "-f", "--looponfail"}

LOG_FILE = re.compile(r"(?i)(\.(log|err|out|tsv)$|(serial|dump|console)[^/]*$)")
LOG_TOOLS = {"cat", "head", "tail"}
FOLLOW = {"-f", "-F", "--follow", "--retry"}
WITH_VALUE = {"-n", "-c", "--lines", "--bytes"}

HEADER = re.compile(r"^=+ (.+?) =+$")
KEEP_SECTIONS = ("FAILURES", "ERRORS", "short test summary info")
ALERT = re.compile(r"(?i)\b(error|errors|warn|warning|exception|fatal|critical)\b|Traceback")


def split_cd(command):
    """`(prefix, rest)` where prefix is a leading `cd DIR && `, or ''."""
    match = CD_PREFIX.match(command)
    return (match.group(0), command[match.end():]) if match else ("", command)


def tokens(rest):
    """The words of a metacharacter-free command, or None if it is not one."""
    if UNSAFE.search(rest):
        return None
    try:
        return shlex.split(rest)
    except ValueError:
        return None


def pytest_decision(words):
    """'allow' or 'ask' when `words` is a pytest run to filter, else None."""
    if not words:
        return None
    exe, args = words[0], words[1:]
    if exe == "pytest" or exe.endswith("/pytest"):
        pass
    elif PYTHON.match(exe) and args[:2] == ["-m", "pytest"]:
        args = args[2:]
    else:
        return None
    if any(arg.split("=")[0] in PYTEST_PASS for arg in args):
        return None
    return "allow" if exe in ALLOWED_EXES else "ask"


def is_log_read(words):
    if not words or words[0] not in LOG_TOOLS:
        return False
    files, skip = [], False
    for word in words[1:]:
        if skip:
            skip = False
        elif word in FOLLOW or word.startswith("--follow"):
            return False
        elif word in WITH_VALUE:
            skip = True
        elif not word.startswith("-"):
            files.append(word)
    return bool(files) and any(LOG_FILE.search(f) for f in files)


def rewrite(tool_input):
    """`(new_command, decision)` for a command worth filtering, else None."""
    command = tool_input.get("command", "").strip()
    if not command or ESCAPE.search(command) or tool_input.get("run_in_background"):
        return None
    prefix, rest = split_cd(command)
    words = tokens(rest)
    if words is None:
        return None
    decision, mode = pytest_decision(words), "--pytest"
    if decision is None:
        if not is_log_read(words):
            return None
        decision, mode = "ask", "--log"
    pipe = f"{shlex.quote(sys.executable)} {shlex.quote(os.path.abspath(__file__))} {mode}"
    return f"set -o pipefail; {prefix}{rest} 2>&1 | {pipe}", decision


def hook():
    try:
        call = json.load(sys.stdin)
        tool_input = call.get("tool_input") or {}
        result = rewrite(tool_input) if call.get("tool_name") == "Bash" else None
    except Exception:
        result = None
    if result is None:
        print("{}")
        return
    command, decision = result
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": "filter_output.py trims the output; append '# raw' for all of it",
        "updatedInput": {**tool_input, "command": command},
    }}))


def capped(lines):
    if len(lines) <= CAP:
        return lines
    head, tail = 60, CAP - 61
    return lines[:head] + [f"... {len(lines) - head - tail} lines cut ..."] + lines[-tail:]


def filter_pytest(lines):
    kept, section, summary = [], None, None
    for line in lines:
        header = HEADER.match(line)
        if header:
            section = header.group(1)
            if re.search(r"\b(passed|failed|error|errors|skipped|no tests ran)\b", section):
                summary = line
                continue
        if section and section.startswith(KEEP_SECTIONS):
            kept.append(line)
    summary = summary or next((line for line in reversed(lines) if line.strip()), "")
    if kept:
        return capped(kept) + [summary]
    clean = re.search(r"\b(passed|skipped|deselected)\b", summary) and not re.search(
        r"\b(failed|error|errors|no tests ran)\b", summary)
    # A clean run needs only its last line; a crash or usage error has no report to keep.
    return [summary] if clean else capped(lines)


def filter_log(lines):
    alerts = [f"{n}: {line}" for n, line in enumerate(lines, 1) if ALERT.search(line)]
    out = [f"{len(alerts)} ERROR/WARN/Traceback lines" + (" (first 50)" if len(alerts) > 50 else "")]
    out += alerts[:50]
    tail = lines[-(CAP - len(out) - 1):]
    return out + [f"--- last {len(tail)} lines ---"] + tail


def run_filter(mode):
    lines = sys.stdin.read().splitlines()
    out = filter_pytest(lines) if mode == "--pytest" else filter_log(lines)
    print(f"[filter_output {mode[2:]}: {len(lines)} lines in, append '# raw' for all]")
    print("\n".join(out))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_filter(sys.argv[1])
    else:
        hook()
