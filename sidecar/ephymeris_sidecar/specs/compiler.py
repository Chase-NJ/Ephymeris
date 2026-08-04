"""The task-spec compiler, behind an import that is allowed to fail.

Everything here is pure and thread-safe, which matters because `compile()` runs on
every keystroke and must therefore run in a worker thread: a 50-150 ms synchronous
compile on the event loop would stall the 20 Hz output flush for all six ports, and
during a live session it would stall the fsync-per-strobe write path. Nothing in
this module touches the filesystem except to read the registries the compiler
already caches.

WHY THE IMPORT MAY STILL FAIL, NOW THAT THE COMPILER IS FIRST-PARTY. It used to be
vendored and reached through a `sys.path` insert, so "the tree is missing" was a
real cause. It is a subpackage now and cannot be missing without the sidecar being
missing. Two causes remain and both are real: `jsonschema` or `pyyaml` failing to
import (`jsonschema` drags the native `rpds-py`, which is the part that actually
fails to install), and a packaged build that dropped the registry data files --
which is exactly what `self_check()` below exists to catch.

The fence is unchanged and was never an argument about where the code lived. The
compiler needs two dependencies the sidecar otherwise does without, a weaker
exception than the `grpcio` one: `grpcio` has the subprocess backend behind it, so
a failed wheel degrades flashing rather than removing it, whereas nothing can stand
in for a compiler. So the fence is drawn around SCOPE instead of capability -- if
the import fails, every `specs.*` handler reports it, the Task screen shows one
banner, and the legacy task.json half of the app and the entire session flow are
untouched. A lab machine that cannot compile a spec can still run sessions.
"""

from __future__ import annotations

import json
from functools import lru_cache
from types import SimpleNamespace
from typing import Any

_IMPORT_ERROR: str | None = None

try:
    from ephymeris_sidecar.taskgraph import paths, templates
    from ephymeris_sidecar.taskgraph.emit import bench, canonical, listing, pack
    from ephymeris_sidecar.taskgraph.pipeline import CompileResult, compile_text
    from ephymeris_sidecar.taskgraph.presentation import placement, presentation
    from ephymeris_sidecar.taskgraph.registries import SCHEMA_DIR, channels
except Exception as exc:  # pragma: no cover - exercised only on a broken install
    _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


#: Defaults for the four knobs `capabilities()` reads, so a half-built topology
#: from a form still answers. They mirror schema/task_spec.v1.json; a knob the
#: caller omits behaves exactly as omitting it from the YAML would.
_TOPOLOGY_DEFAULTS = {
    "n_sampling_stages": 1,
    "response_mode": "n_alternative",
    "commit_hold": True,
    "retention_delay": False,
}

DEFAULT_TEMPLATE = ("four_epoch", 2)


def available() -> tuple[bool, str | None]:
    """(importable, why not). Cheap; says nothing about whether it WORKS."""
    return (_IMPORT_ERROR is None, _IMPORT_ERROR)


@lru_cache(maxsize=1)
def self_check() -> tuple[bool, str | None]:
    """(usable, why not) -- proved by compiling a real spec, not by importing.

    The distinction is not pedantic, and a packaged build is where it bites. The
    compiler is shipped as data files, so its own dependencies have to be named by
    hand in the PyInstaller invocation; get that half right and the import
    succeeds, get the other half wrong and every compile fails on a metaschema
    `jsonschema` could not load. An "is it there" check would have reported ready.

    So this GENERATES a task and runs the whole pipeline over it -- schema
    validation, the linter, the packer -- and only then says yes. Once, at
    startup, cached -- about 60 ms, paid on a path that already opens a database.

    Generating rather than reading a shipped file is strictly stronger, and it
    is also the only option: nothing ships as a spec. One probe now exercises
    the paradigm registry, the template, the channel registry composed with the
    active pinout, the strobe vocabulary, jsonschema's metaschema data, every
    lint pass and the packer. Those are exactly the data files a freeze can drop
    -- and the first thing an operator would otherwise hit is an empty New Task
    screen with no explanation.
    """
    ok, why = available()
    if not ok:
        return ok, why
    try:
        from ephymeris_sidecar.taskgraph import paradigms

        probe = paradigms.canonical()
        text = paradigms.to_yaml(paradigms.skeleton(probe, spec_id="self_check_probe"))
        result = compile(text, spec_id="self_check_probe")
        if not result.ok:
            return False, f"the {probe.id} skeleton did not compile: {result.bag.render()}"
        table_bytes(result)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, None


def require() -> None:
    if _IMPORT_ERROR is not None:
        raise SpecCompilerUnavailable(_IMPORT_ERROR)


class SpecCompilerUnavailable(RuntimeError):
    """The compiler could not be imported or is unusable. Carries the reason."""


def compile(text: str, *, spec_id: str | None = None) -> CompileResult:
    """Compile a document. Never raises for a spec problem -- read `.bag`.

    Takes the TEXT rather than a parsed document on purpose: the LOAD pass checks
    things that only exist before parsing, and the editor must validate exactly the
    bytes it is about to save.
    """
    require()
    return compile_text(text, spec_id=spec_id)


def capabilities_for(
    topology: dict[str, Any],
    *,
    template: str | None = None,
    template_version: int | None = None,
) -> Any:
    """What this topology produces: outcome classes and required timing ids.

    A pure function of four scalars, so the form calls it on every knob change and
    re-gates its timing rows and outcome cards before any compile returns. That
    immediacy is the entire argument for capabilities() being a function rather
    than a static table.
    """
    require()
    name = template or topology.get("template") or DEFAULT_TEMPLATE[0]
    version = template_version or topology.get("template_version") or DEFAULT_TEMPLATE[1]
    knobs = {**_TOPOLOGY_DEFAULTS, **{k: v for k, v in topology.items() if v is not None}}
    return templates.load(name, int(version)).capabilities(SimpleNamespace(**knobs))


def templates_available() -> tuple[tuple[str, int], ...]:
    require()
    return templates.available()


def compiler_root() -> Any:
    """Where the compiler was imported from. Logged at startup."""
    require()
    return paths.PACKAGE_DIR


def registries() -> dict[str, Any]:
    """Everything a form needs to populate its pickers, in one call.

    Serves the registry FILES rather than a re-serialisation of the parsed views,
    for two reasons. They are the same bytes the compiler validates against, so a
    strobe picker cannot offer a code the compiler then rejects. And they carry the
    prose the parsed views drop -- every strobe's rationale, every channel's kind
    and well, every limit's justification -- which is most of what makes a picker
    readable rather than a list of numbers.

    CHANNELS ARE THE ONE EXCEPTION, and it strengthens the rule rather than
    weakening it. A channel is now two files -- what it means, and where it is on
    this box -- so there is no single file to serve. What goes on the wire is the
    COMPOSED view: the compiler's own resolved `ChannelMap`, carrying the logical
    fields joined to the active pinout. A picker therefore cannot offer a channel
    the compiler would fail to place, which is a stronger guarantee than serving
    either half, and the shape the frontend reads is unchanged.

    One call on route mount. The frontend must never hold its own copy.
    """
    require()
    return {
        "schema": _registry("task_spec.v1.json"),
        "overlay": presentation(),
        "strobes": _registry("strobe_vocab.v1.json"),
        "channels": channels().to_json(),
        "limits": _registry("limits.v1.json"),
        "templates": [
            {"name": n, "version": v, "sourceHash": templates.source_hash(n, v)}
            for n, v in templates.available()
        ],
    }


@lru_cache(maxsize=8)
def _registry(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text())


def diagnostic_placement(location: str | None) -> tuple[str, str | None]:
    """Where a diagnostic belongs on screen. See taskgraph/presentation.py."""
    require()
    return placement(location)


def render_listing(result: CompileResult) -> str:
    """The checked-in review artifact, verbatim -- what a topology diff is against."""
    require()
    return listing.render(result.table, result.bag)


def render_lint(result: CompileResult) -> str:
    require()
    return listing.render_lint(result.bag, result.table.spec_id if result.table else "?")


def render_bench(result: CompileResult) -> str:
    require()
    return bench.render(result.table)


def table_json(result: CompileResult) -> dict:
    require()
    return canonical.to_dict(result.table)


def table_bytes(result: CompileResult) -> tuple[bytes, int]:
    """(packed table, crc32) -- the bytes a board receives."""
    require()
    blob = pack.pack(result.table)
    return blob, pack.crc32(blob)
