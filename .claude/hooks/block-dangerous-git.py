#!/usr/bin/env python3
"""PreToolUse guard for the Review II overnight run.

Started from mattpocock/skills' git-guardrails-claude-code and tightened for an
unattended run where agents act as the repo's admin. Agents may push to
`review-ii/<node>` and squash-merge into `review-ii/integration`; nothing may
reach `main`, rewrite history, discard work, or change the repo's settings.

The rulesets on GitHub are the real gate. This hook exists because the agents
hold an admin token, and an admin can edit a ruleset; so it refuses anything
that writes through the API. It fails closed: a command it cannot parse, or a
PR whose base it cannot look up, is refused.

Exit 2 with a reason on stderr blocks the call; exit 0 allows it.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys

PROTECTED = "main"
INTEGRATION = "review-ii/integration"
PUSHABLE = re.compile(r"^review-ii/(?!integration$)[A-Za-z0-9._/-]+$")

# Split a command line into simple commands. Quotes are respected by shlex,
# so this only splits on separators outside them.
SEPARATORS = {"&&", "||", ";", "|", "&", "\n", "(", ")", "{", "}"}
WRAPPERS = {"env", "command", "builtin", "exec", "nohup", "time", "xargs", "sudo"}
SHELLS = {"sh", "bash", "zsh", "dash"}


class Blocked(Exception):
    pass


def block(reason: str) -> None:
    raise Blocked(reason)


HEREDOC = re.compile(
    r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1([^\n]*)\n(.*?)\n[ \t]*\2[ \t]*(?=\n|\)|$)", re.S
)
INTERPRETERS = SHELLS | {"python", "python3", "node", "perl", "ruby"}


def split_heredocs(command: str) -> tuple[str, list[str]]:
    """Cut heredoc bodies out of the command line, and return the ones a shell
    or interpreter on the same line will run so they are checked too. The rest
    (a commit message, a PR body) are data, and prose would trip the lexer."""
    executed: list[str] = []

    def cut(match: re.Match[str]) -> str:
        line_start = command.rfind("\n", 0, match.start()) + 1
        line = command[line_start : match.start()] + match.group(3)
        programs = {w.rsplit("/", 1)[-1] for w in re.split(r"[\s|;&()]+", line) if w}
        if programs & INTERPRETERS:
            executed.append(match.group(4))
        return "<< " + match.group(2) + match.group(3)

    return HEREDOC.sub(cut, command), executed


def tokenize(command: str) -> list[list[str]]:
    # A newline separates commands like `;` does, so it is punctuation here;
    # inside quotes it stays part of the word.
    lexer = shlex.shlex(command, posix=True, punctuation_chars="&|;()<>\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = list(lexer)
    commands: list[list[str]] = [[]]
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if set(token) <= set("&|;()\n"):
            commands.append([])
        elif set(token) <= set("<>&|") and ("<" in token or ">" in token):
            # A redirection: drop it, its target, and a file descriptor in front
            # (`2>&1` lexes as `2`, `>&`, `1`).
            if commands[-1] and commands[-1][-1].isdigit():
                commands[-1].pop()
            skip_next = True
        else:
            commands[-1].append(token)
    return [c for c in commands if c]


def strip_prefix(argv: list[str]) -> list[str]:
    """Drop `FOO=bar`, `env`, `command` and friends in front of the program."""
    i = 0
    while i < len(argv):
        word = argv[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", word) or word in WRAPPERS:
            i += 1
        elif word.startswith("-") and i > 0 and argv[i - 1] in WRAPPERS:
            i += 1
        else:
            break
    return argv[i:]


def run(args: list[str], cwd: str | None) -> str:
    out = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"{args[0]} exited {out.returncode}")
    return out.stdout.strip()


# --- git -------------------------------------------------------------------


def git_parts(argv: list[str], cwd: str | None) -> tuple[str, list[str], str | None]:
    """Return (subcommand, its args, effective cwd), skipping `-C dir`, `-c k=v`."""
    i = 1
    while i < len(argv) and argv[i].startswith("-"):
        if argv[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") and i + 1 < len(argv):
            if argv[i] == "-C":
                cwd = argv[i + 1] if argv[i + 1].startswith("/") or not cwd else f"{cwd}/{argv[i + 1]}"
            i += 2
        else:
            i += 1
    if i >= len(argv):
        return "", [], cwd
    return argv[i], argv[i + 1 :], cwd


def short_ref(ref: str) -> str:
    return re.sub(r"^refs/heads/", "", ref)


def check_git(argv: list[str], cwd: str | None) -> None:
    sub, args, cwd = git_parts(argv, cwd)
    flags = [a for a in args if a.startswith("-")]

    if sub == "reset" and "--hard" in args:
        block("git reset --hard discards work")
    if sub == "clean" and any(re.match(r"^-[a-zA-Z]*f", a) or a == "--force" for a in flags):
        block("git clean -f deletes untracked files")
    if sub == "branch":
        force_delete = any(re.match(r"^-[a-zA-Z]*D", a) for a in flags)
        deleting = "--delete" in args or any(re.match(r"^-[a-zA-Z]*d", a) for a in flags)
        forcing = "--force" in args or any(re.match(r"^-[a-zA-Z]*f", a) for a in flags)
        if force_delete or (deleting and forcing):
            block("git branch -D force-deletes a branch")
    if sub in ("checkout", "restore") and any(a in (".", "./", ":/") for a in args):
        block(f"git {sub} . discards work")
    if sub == "push":
        check_push(args, cwd)


def check_push(args: list[str], cwd: str | None) -> None:
    for a in args:
        if a in ("-f", "--force", "--mirror", "--all", "--delete", "-d", "--prune", "--tags") or a.startswith(
            ("--force-with-lease", "--force-if-includes")
        ) or (re.match(r"^-[a-zA-Z]+$", a) and ("f" in a or "d" in a)):
            block(f"git push {a} is not allowed")
    positional = [a for a in args if not a.startswith("-")]
    # Options that take a value would otherwise look positional.
    for opt in ("--repo", "-o", "--push-option", "--receive-pack", "--exec"):
        if opt in args:
            block(f"git push {opt} is not allowed")
    refspecs = positional[1:]
    if not refspecs:
        # A bare push goes wherever push.default sends the current branch.
        try:
            target = run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{push}"], cwd)
        except Exception as exc:  # noqa: BLE001 - unknown target: refuse
            block(f"cannot tell where a bare git push would go ({exc}); name the branch")
        target = target.split("/", 1)[1] if "/" in target else target
        refspecs = [f"HEAD:{target}"]
    for spec in refspecs:
        if spec.startswith("+"):
            block(f"forced refspec {spec}")
        src, _, dst = spec.partition(":")
        if _ and not src:
            block(f"{spec} deletes a remote branch")
        dst = dst or src
        if dst == "HEAD" or not dst:
            try:
                dst = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
            except Exception as exc:  # noqa: BLE001
                block(f"cannot resolve HEAD ({exc})")
        dst = short_ref(dst)
        if dst == PROTECTED:
            block(f"pushing to {PROTECTED} is not allowed; open a PR to {INTEGRATION}")
        if not PUSHABLE.match(dst):
            block(f"push target {dst!r} is not a review-ii/<node> branch")


# --- gh --------------------------------------------------------------------


def option(args: list[str], *names: str) -> str | None:
    for i, a in enumerate(args):
        for n in names:
            if a == n and i + 1 < len(args):
                return args[i + 1]
            if a.startswith(n + "="):
                return a.split("=", 1)[1]
    return None


def check_gh(argv: list[str], cwd: str | None) -> None:
    args = argv[1:]
    words = [a for a in args if not a.startswith("-")]
    group = words[0] if words else ""
    verb = words[1] if len(words) > 1 else ""

    if group == "repo" and verb in ("delete", "edit", "rename", "archive", "unarchive", "set-default"):
        block(f"gh repo {verb} changes the repository")
    if group in ("ruleset", "secret", "variable") and verb not in ("list", "view", "check", ""):
        block(f"gh {group} {verb} changes repository configuration")
    if group == "workflow" and verb in ("disable", "enable"):
        block(f"gh workflow {verb} changes CI")
    if group == "api":
        check_api(args)
    if group == "pr" and verb == "create":
        base = option(args, "--base", "-B")
        if base is None:
            block(f"gh pr create needs an explicit --base {INTEGRATION} (the default is {PROTECTED})")
        if base != INTEGRATION:
            block(f"PRs may only target {INTEGRATION}, not {base!r}")
    if group == "pr" and verb == "edit":
        base = option(args, "--base", "-B")
        if base is not None and base != INTEGRATION:
            block(f"PRs may only target {INTEGRATION}, not {base!r}")
    if group == "pr" and verb == "review" and any(a in ("--approve", "-a") for a in args):
        block("agents do not approve PRs")
    if group == "pr" and verb == "merge":
        check_merge(args, cwd)


def check_api(args: list[str]) -> None:
    method = (option(args, "-X", "--method") or "").upper()
    endpoint = next((a for a in args[1:] if not a.startswith("-")), "")
    sends_fields = any(
        a in ("-f", "-F", "--field", "--raw-field", "--input") or a.startswith(("--field=", "--raw-field=", "--input="))
        for a in args
    )
    if endpoint == "graphql":
        query = " ".join(args)
        if re.search(r"\bmutation\b", query):
            block("gh api graphql mutations are not allowed")
        return
    if method and method != "GET":
        block(f"gh api -X {method} writes to GitHub; use the gh subcommand for the action")
    if sends_fields and method != "GET":
        block("gh api with fields defaults to POST; pass -X GET to read")


def check_merge(args: list[str], cwd: str | None) -> None:
    if "--admin" in args:
        block("gh pr merge --admin bypasses the rulesets")
    if "--merge" in args or "-m" in args or "--rebase" in args or "-r" in args:
        block("only --squash merges are allowed")
    if "--squash" not in args and "-s" not in args:
        block("gh pr merge needs --squash")
    # Values of options that take one (--body, --subject, ...) are not the PR.
    skip = set()
    for i, a in enumerate(args):
        if a in ("-b", "--body", "-F", "--body-file", "-t", "--subject", "-A", "--author-email", "--match-head-commit", "-R", "--repo"):
            if i + 1 < len(args):
                skip.add(i + 1)
    words = [a for i, a in enumerate(args) if i >= 2 and not a.startswith("-") and i not in skip]
    selector = words[0] if words else None
    repo = option(args, "-R", "--repo")
    query = ["gh", "pr", "view"] + ([selector] if selector else []) + (["-R", repo] if repo else []) + [
        "--json",
        "baseRefName",
        "-q",
        ".baseRefName",
    ]
    try:
        base = run(query, cwd)
    except Exception as exc:  # noqa: BLE001 - unknown base: refuse
        block(f"cannot look up the PR's base ({exc}); refusing to merge")
    if base != INTEGRATION:
        block(f"agents may only merge into {INTEGRATION}; this PR's base is {base!r}")


# --- driver ----------------------------------------------------------------


def check(command: str, cwd: str | None, depth: int = 0) -> None:
    if depth > 4:
        block("command nests shells too deeply to check")
    command, executed = split_heredocs(command)
    for body in executed:
        check(body, cwd, depth + 1)
    try:
        commands = tokenize(command)
    except ValueError as exc:
        if re.search(r"\b(git|gh)\b", command):
            block(f"cannot parse a command that runs git or gh ({exc})")
        return
    for argv in commands:
        argv = strip_prefix(argv)
        if not argv:
            continue
        prog = argv[0].rsplit("/", 1)[-1]
        if prog == "cd" and len(argv) > 1:
            cwd = argv[1] if argv[1].startswith("/") or not cwd else f"{cwd}/{argv[1]}"
            continue
        if prog in SHELLS and "-c" in argv:
            i = argv.index("-c")
            if i + 1 < len(argv):
                check(argv[i + 1], cwd, depth + 1)
            continue
        if prog == "eval":
            check(" ".join(argv[1:]), cwd, depth + 1)
            continue
        if prog == "git":
            check_git(argv, cwd)
        elif prog == "gh":
            check_gh(argv, cwd)
        else:
            # A git or gh line hidden in an argument of another program
            # (python -c, a string fed to sh) still gets checked. A program
            # that builds the argv itself (subprocess.run(["git", "push", ...]))
            # is beyond a text check; the rulesets on GitHub catch that.
            for word in argv:
                if re.search(r"(^|[\s;&|(`$'\"])(git|gh)\s+(push|reset|clean|branch|checkout|restore|pr|api|repo|ruleset)\b", word):
                    check(word, cwd, depth + 1)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0
    if payload.get("tool_name", "Bash") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    try:
        check(command, payload.get("cwd"))
    except Blocked as reason:
        print(f"BLOCKED by .claude/hooks/block-dangerous-git.py: {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
