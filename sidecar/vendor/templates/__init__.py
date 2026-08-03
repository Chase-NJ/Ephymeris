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
import importlib
from pathlib import Path
from types import ModuleType

TEMPLATE_DIR = Path(__file__).resolve().parent


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
    """Import templates/<name>/v<version>.py."""
    path = TEMPLATE_DIR / name / f"v{version}.py"
    if not path.is_file():
        listed = ", ".join(f"{n} v{v}" for n, v in available())
        raise TemplateNotFound(
            f"no template {name!r} version {version}. Available: {listed or 'none'}"
        )
    return importlib.import_module(f"templates.{name}.v{version}")


def source_hash(name: str, version: int) -> str:
    """SHA-256 of the template source, truncated.

    Recorded in the listing so that editing a pinned template -- which the
    file-per-version rule forbids -- shows up as a diff in the checked-in artifact
    rather than as a silent change of every task that pins it.
    """
    path = TEMPLATE_DIR / name / f"v{version}.py"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
