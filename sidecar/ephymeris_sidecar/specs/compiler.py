"""The vendored Task-Graph compiler, behind an import that is allowed to fail.

Everything here is pure and thread-safe, which matters because `compile()` runs on
every keystroke and must therefore run in a worker thread: a 50-150 ms synchronous
compile on the event loop would stall the 20 Hz output flush for all six ports, and
during a live session it would stall the fsync-per-strobe write path. Nothing in
this module touches the filesystem except to read the registries the compiler
already caches.

WHY THE IMPORT MAY FAIL, AND WHAT HAPPENS THEN. The compiler needs `jsonschema` and
`pyyaml`, which is a real weakening of the sidecar's two-dependency rule and a
weaker exception than the `grpcio` one: `grpcio` has the subprocess backend behind
it, so a failed wheel degrades flashing rather than removing it, whereas nothing can
stand in for a compiler. So the fence is drawn around SCOPE instead of capability --
if the import fails, every `specs.*` handler reports it, the Task screen shows one
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
    from . import _vendor  # noqa: F401  -- side effect: puts the vendor tree on sys.path

    import templates
    from taskgraph.emit import bench, canonical, listing, pack
    from taskgraph.pipeline import CompileResult, compile_text
    from taskgraph.presentation import placement, presentation
    from taskgraph.registries import SCHEMA_DIR
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

    So this runs the whole pipeline over a bundled spec, through schema
    validation, the linter and the packer, and only then says yes. Once, at
    startup, cached -- about 60 ms, paid on a path that already opens a database.
    """
    ok, why = available()
    if not ok:
        return ok, why
    try:
        probe = sorted(bundled_specs_dir().glob("*.yaml"))[0]
        result = compile(probe.read_text(), spec_id=probe.stem)
        if not result.ok:
            return False, f"{probe.name} did not compile: {result.bag.render()}"
        table_bytes(result)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, None


def bundled_specs_dir() -> Any:
    """The shipped specs. Read-only -- user edits live under the app data dir."""
    require()
    return _vendor.ROOT / "specs"


def require() -> None:
    if _IMPORT_ERROR is not None:
        raise SpecCompilerUnavailable(_IMPORT_ERROR)


class SpecCompilerUnavailable(RuntimeError):
    """The vendored compiler could not be imported. Carries the original error."""


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


def vendor_root() -> Any:
    """Where the compiler was imported from. Logged at startup; see _vendor.py."""
    require()
    return _vendor.ROOT


def template_source_hash(name: str, version: int) -> str:
    require()
    return templates.source_hash(name, version)


def registries() -> dict[str, Any]:
    """Everything a form needs to populate its pickers, in one call.

    Serves the registry FILES rather than a re-serialisation of the parsed views,
    for two reasons. They are the same bytes the compiler validates against, so a
    strobe picker cannot offer a code the compiler then rejects. And they carry the
    prose the parsed views drop -- every strobe's rationale, every channel's kind
    and well, every limit's justification -- which is most of what makes a picker
    readable rather than a list of numbers.

    One call on route mount. The frontend must never hold its own copy.
    """
    require()
    return {
        "schema": _registry("task_spec.v1.json"),
        "overlay": presentation(),
        "strobes": _registry("strobe_vocab.v1.json"),
        "channels": _registry("channels.v1.json"),
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
