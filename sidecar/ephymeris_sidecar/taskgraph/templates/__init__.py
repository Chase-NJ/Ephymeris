"""Versioned epoch templates.

A template turns layer-1 knobs into a node and edge list. Task authors never write
a node: the set of representable graphs is exactly the image of these functions
over the topology enum, which is what makes compilation, validation and the
eventual UI tractable (docs/decisions.md D1).

VERSIONING IS BY FILE. `four_epoch/v1.py` is never edited once a spec pins it; a
change copies to `v2.py`. `topology.template_version` therefore names a file, and
"a template edit cannot silently change an existing task's graph" is a property of
the filesystem rather than a promise. The listing header records the template's
source hash so a violation is visible in review.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from types import ModuleType

from ..paths import TEMPLATE_DIR


class TemplateNotFound(LookupError):
    pass


def available() -> tuple[tuple[str, int], ...]:
    """Every (name, version) present on disk, sorted.

    The one enumeration; load()'s error message and any GUI template picker both
    read this rather than repeating the glob.
    """
    return tuple(
        sorted(
            (d.name, int(p.stem[1:]))
            for d in TEMPLATE_DIR.iterdir()
            if d.is_dir() and not d.name.startswith("_")
            for p in d.glob("v*.py")
            if p.stem[1:].isdigit()
        )
    )


def load(name: str, version: int) -> ModuleType:
    """Import templates/<name>/v<version>.py.

    LOADED FROM THE PATH, NOT THE IMPORT SYSTEM -- and the module name is still
    the canonical dotted one, cached in `sys.modules`, so there is exactly one
    module object per version exactly as before. Only the finder changes.

    The reason is `source_hash()` below. It reads the file's own bytes, and the
    listing records that hash so that editing a pinned template -- which the
    file-per-version rule forbids (D14) -- shows up as a diff. If `load()` went
    through the import system it could execute a cached bytecode file while
    `source_hash()` hashed the source beside it, and the recorded hash would be
    a claim about bytes that never ran. Reading both from one path makes the
    listing's `template_hash` a guarantee rather than an assumption.
    """
    path = TEMPLATE_DIR / name / f"v{version}.py"
    if not path.is_file():
        listed = ", ".join(f"{n} v{v}" for n, v in available())
        raise TemplateNotFound(
            f"no template {name!r} version {version}. Available: {listed or 'none'}"
        )
    mod_name = f"{__name__}.{name}.v{version}"
    cached = sys.modules.get(mod_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable for a real file
        raise TemplateNotFound(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def source_hash(name: str, version: int) -> str:
    """SHA-256 of the template source, truncated.

    Recorded in the listing so that editing a pinned template -- which the
    file-per-version rule forbids -- shows up as a diff in the checked-in artifact
    rather than as a silent change of every task that pins it.
    """
    path = TEMPLATE_DIR / name / f"v{version}.py"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
