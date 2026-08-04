"""taskgraph — compile, lint, and keep the generated artifacts honest.

`--check` means the same thing everywhere: produce nothing, exit 1 if what is on
disk differs from what would be generated. That uniformity is what lets CI be
three obvious commands rather than a script nobody reads.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ephymeris_sidecar.taskgraph.emit.listing import render, render_lint
from ephymeris_sidecar.taskgraph.errors import Severity
from ephymeris_sidecar.taskgraph.pipeline import compile_spec

from . import paths


def _listing_path(spec: Path) -> Path:
    return spec.with_suffix(".table.txt")


def _lint_path(spec: Path) -> Path:
    return spec.with_suffix(".lint.txt")


def _report(result, path: Path, *, quiet: bool = False) -> None:
    if not quiet:
        text = result.bag.render()
        if text:
            print(text)
    status = "ok" if result.ok else "FAILED"
    print(f"{path.name}: {status} — {result.bag.summary()}")


def cmd_compile(args) -> int:
    failed = 0
    for spec_path in _specs(args.specs):
        result = compile_spec(spec_path, strict=args.strict)
        _report(result, spec_path)
        if not result.ok:
            failed += 1
            continue
        _listing_path(spec_path).write_text(render(result.table, result.bag))
        _lint_path(spec_path).write_text(render_lint(result.bag, result.table.spec_id))

        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        from ephymeris_sidecar.taskgraph.emit.canonical import to_json
        from ephymeris_sidecar.taskgraph.emit.pack import crc32, pack

        (out / f"{result.table.spec_id}.table.json").write_text(to_json(result.table))

        #: The bytes a board receives, and the only artifact the CRC is defined
        #: over. Emitted even though nothing uploads it yet, because writing it is
        #: what forces the Python and C++ layouts to be reconciled rather than
        #: merely believed to agree.
        blob = pack(result.table)
        (out / f"{result.table.spec_id}.table.bin").write_bytes(blob)
        print(f"  {len(blob)} bytes on the wire, crc32={crc32(blob):#010x}")
    return 1 if failed else 0


def cmd_lint(args) -> int:
    failed = 0
    for spec_path in _specs(args.specs):
        result = compile_spec(spec_path, strict=args.strict)
        _report(result, spec_path)
        failed += 0 if result.ok else 1
    return 1 if failed else 0


def cmd_listing(args) -> int:
    """--check: the goldens must match what the compiler produces now.

    This is the guard that makes the checked-in listing meaningful. Without it a
    template change would silently diverge from the artifact everyone reviews, and
    the listing would become decoration.
    """
    stale = []
    for spec_path in _specs(args.specs):
        result = compile_spec(spec_path)
        if not result.ok:
            print(result.bag.render())
            print(f"{spec_path.name}: does not compile")
            return 1
        for path, wanted in (
            (_listing_path(spec_path), render(result.table, result.bag)),
            (_lint_path(spec_path), render_lint(result.bag, result.table.spec_id)),
        ):
            current = path.read_text() if path.exists() else None
            if current != wanted:
                stale.append(path)
    if stale:
        names = ", ".join(str(p.relative_to(paths.repo_root())) for p in stale)
        print(f"stale checked-in artifact(s): {names}", file=sys.stderr)
        print("run `taskgraph compile specs/*.yaml` and commit the result", file=sys.stderr)
        return 1
    print("listings and lint baselines are current")
    return 0


def cmd_show(args) -> int:
    result = compile_spec(args.spec)
    if not result.ok:
        print(result.bag.render())
        return 1
    print(render(result.table, result.bag))
    return 0


def cmd_codegen(args) -> int:
    from ephymeris_sidecar.taskgraph.codegen import generate_all

    return generate_all(check=args.check)


def _baud(value: str) -> int:
    """`auto` is 0, which _link reads as "detect"."""
    return 0 if value.lower() == "auto" else int(value)


def _link(args):
    from ephymeris_sidecar.taskgraph.transport.link import ProcessLink, SerialLink

    #: --board runs the off-target simulator instead of opening a port. It is the
    #: same receiver an ATmega2560 runs, so `taskgraph upload --board ./tg_board`
    #: exercises the real conversation with no hardware -- which is how this is
    #: tested, and how someone without a box on their desk can check a spec fits.
    if args.board:
        return ProcessLink([args.board])
    if not args.port:
        raise SystemExit("give --port <device> (or --board <binary> to run off-target)")
    if args.baud == 0:
        #: --baud auto. The fleet contains boxes at two rates during the rollout
        #: -- the interpreter firmware opens at 115200 while the eight behaviour
        #: sketches still open at 9600 -- so "which rate is this box at" is a real
        #: question with a cheap answer.
        from ephymeris_sidecar.taskgraph.transport.client import detect

        baud = detect(lambda b: SerialLink(args.port, b))
        print(f"detected {baud} baud")
        return SerialLink(args.port, baud)
    return SerialLink(args.port, args.baud)


def cmd_upload(args) -> int:
    from ephymeris_sidecar.taskgraph.emit.pack import crc32, pack
    from ephymeris_sidecar.taskgraph.transport import UploadError
    from ephymeris_sidecar.taskgraph.transport.caps import CapabilityError
    from ephymeris_sidecar.taskgraph.transport.client import upload

    result = compile_spec(Path(args.spec), strict=args.strict)
    _report(result, Path(args.spec), quiet=True)
    if not result.ok:
        return 1

    blob = pack(result.table)
    print(f"{result.table.spec_id}: {len(blob)} bytes, crc32={crc32(blob):#010x}")
    if args.dry_run:
        #: Compile and pack, stop before the wire. Useful for checking a spec fits
        #: before walking to the rig.
        return 0

    try:
        with _link(args) as link:
            r = upload(link, result.table, packed=blob)
    except (UploadError, CapabilityError) as exc:
        print(f"\nupload failed: {exc}", file=sys.stderr)
        return 1

    for line in r.caps.lines:
        print(f"  {line}")
    for note in r.notes:
        print(f"  note: {note}")
    print(
        f"\naccepted: crc={r.crc:#010x} digest={r.digest:#010x} "
        f"({r.chunks} chunks, {r.seconds * 1000:.0f} ms)"
    )
    print("  crc  — the bytes arrived intact")
    print("  digest — and were decoded into the right fields")
    return 0


def cmd_probe(args) -> int:
    """What a box says about itself. Changes nothing on it."""
    from ephymeris_sidecar.taskgraph.transport import UploadError
    from ephymeris_sidecar.taskgraph.transport.client import probe

    try:
        with _link(args) as link:
            banner, caps = probe(link)
    except UploadError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    for line in banner:
        print(line)
    if not caps.present:
        print("\nno CAP line: un-migrated firmware, PROTO=1, bare-START path only")
        return 0
    print(f"\n{len(caps.values) + len(caps.text)} capabilities announced")
    return 0


def cmd_bench(args) -> int:
    """What to put a probe on, and what it should read."""
    from ephymeris_sidecar.taskgraph.emit.bench import render

    result = compile_spec(Path(args.spec))
    if not result.ok:
        _report(result, Path(args.spec))
        return 1
    text = render(result.table)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text, end="")
    return 0


def cmd_rules(args) -> int:
    """Print the rule table. Useful when someone pastes a code into an issue."""
    from ephymeris_sidecar.taskgraph.lint import REGISTRY, load_all_rules

    load_all_rules()
    for r in REGISTRY.all():
        mark = {Severity.ERROR: "E", Severity.WARN: "W", Severity.INFO: "i"}[r.severity]
        dec = f"  [{r.decision}]" if r.decision else ""
        print(f"{r.code} {mark} {r.pass_.name:<8} {r.name}{dec}")
        print(f"        {r.help}")
    return 0


def _specs(patterns) -> list[Path]:
    out: list[Path] = []
    for p in patterns:
        path = Path(p)
        out.extend(sorted(path.parent.glob(path.name)) if "*" in p else [path])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="taskgraph", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compile", help="compile specs and rewrite their checked-in artifacts")
    c.add_argument("specs", nargs="+")
    c.add_argument("-o", "--out", default="build")
    c.add_argument("--strict", action="store_true", help="treat warnings as errors")
    c.set_defaults(fn=cmd_compile)

    c = sub.add_parser("lint", help="check specs without writing anything")
    c.add_argument("specs", nargs="+")
    c.add_argument("--strict", action="store_true")
    c.set_defaults(fn=cmd_lint)

    c = sub.add_parser("listing", help="verify the checked-in listings are current")
    c.add_argument("specs", nargs="+")
    c.add_argument("--check", action="store_true", default=True)
    c.set_defaults(fn=cmd_listing)

    c = sub.add_parser("show", help="print a spec's state table")
    c.add_argument("spec")
    c.set_defaults(fn=cmd_show)

    c = sub.add_parser("codegen", help="emit or verify the generated headers")
    c.add_argument("--check", action="store_true")
    c.set_defaults(fn=cmd_codegen)

    def _wire(c):
        from ephymeris_sidecar.taskgraph.registries import limits

        c.add_argument("--port", help="serial device, e.g. /dev/cu.usbmodem11101")
        c.add_argument("--board", help="run an off-target board simulator instead")
        c.add_argument(
            "--baud", type=_baud, default=limits().TG_BAUD_RATE,
            help="rate, or 'auto' to try each candidate and keep the one that answers",
        )
        return c

    c = _wire(sub.add_parser("upload", help="compile a spec and put it on a board"))
    c.add_argument("spec")
    c.add_argument("--strict", action="store_true")
    c.add_argument("--dry-run", action="store_true",
                   help="compile and pack, but do not open the port")
    c.set_defaults(fn=cmd_upload)

    c = _wire(sub.add_parser("probe", help="read a board's CAP banner and stop"))
    c.set_defaults(fn=cmd_probe)

    c = sub.add_parser("bench", help="the bench card: probe points and expected numbers")
    c.add_argument("spec")
    c.add_argument("-o", "--out", help="write to a file instead of stdout")
    c.set_defaults(fn=cmd_bench)

    c = sub.add_parser("rules", help="list every linter rule")
    c.set_defaults(fn=cmd_rules)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
