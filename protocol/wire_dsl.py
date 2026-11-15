"""The tiny type language `protocol/schema.py` is written in.

Pure data — no emission logic lives here (that is `generate.py`) and nothing
here runs at app runtime. Deliberately much smaller than JSON Schema: the wire
only ever carries the shapes below, and every construct must be expressible in
both a TypeScript type and a runtime-checkable Python spec, so anything fancier
would be a liability rather than a feature.

Runs on any Python ≥ 3.9 so a bare system interpreter can generate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Tuple, Union


# --- Type expressions ------------------------------------------------------


@dataclass(frozen=True)
class Prim:
    """A JSON primitive. `int` and `float` both render to TS `number`, but the
    Python validator keeps them distinct (and rejects `bool` for either)."""

    kind: str  # "str" | "int" | "float" | "bool" | "any" | "null"


STR = Prim("str")
INT = Prim("int")
FLOAT = Prim("float")
BOOL = Prim("bool")
#: Escape hatch for genuinely open values (Task Profile defaults, error detail).
ANY = Prim("any")
NULL = Prim("null")


@dataclass(frozen=True)
class Lit:
    """A closed set of string literals — `"rx" | "tx"`."""

    values: Tuple[str, ...]


def lit(*values: str) -> Lit:
    return Lit(tuple(values))


@dataclass(frozen=True)
class ListOf:
    item: "Ty"


@dataclass(frozen=True)
class MapOf:
    """A string-keyed map with uniform values — TS `Record<string, T>`."""

    value: "Ty"


@dataclass(frozen=True)
class UnionOf:
    options: Tuple["Ty", ...]


def union(*options: "Ty") -> UnionOf:
    return UnionOf(tuple(options))


def nullable(ty: "Ty") -> UnionOf:
    return UnionOf((ty, NULL))


@dataclass(frozen=True)
class Ref:
    """A reference to a named shape declared elsewhere in the schema."""

    name: str


@dataclass(frozen=True)
class Field:
    name: str
    ty: "Ty"
    #: Optional means the key may be absent — distinct from nullable.
    optional: bool = False
    doc: Optional[str] = None


def f(name: str, ty: "Ty", optional: bool = False, doc: Optional[str] = None) -> Field:
    return Field(name, ty, optional, doc)


@dataclass(frozen=True)
class Obj:
    fields: Tuple[Field, ...]


def obj(*fields: Field) -> Obj:
    return Obj(tuple(fields))


Ty = Union[Prim, Lit, ListOf, MapOf, UnionOf, Ref, Obj]


# --- Named declarations ----------------------------------------------------


@dataclass(frozen=True)
class Shape:
    """A named payload type. An `Obj` body becomes a TS interface; anything
    else becomes a type alias."""

    name: str
    ty: Ty
    doc: Optional[str] = None


@dataclass(frozen=True)
class Command:
    """One client→server command. `args=None` means the command takes none."""

    name: str
    args: Optional[Obj] = None
    result: Ty = ANY
    doc: Optional[str] = None
    #: Grouping comment emitted above this entry in both mirrors.
    section: Optional[str] = None

    @property
    def const(self) -> str:
        return _const_name(self.name)


@dataclass(frozen=True)
class Event:
    """One server→client event."""

    name: str
    data: Ty = ANY
    doc: Optional[str] = None

    @property
    def const(self) -> str:
        return _const_name(self.name)


@dataclass(frozen=True)
class ErrorCode:
    name: str
    doc: Optional[str] = None


@dataclass(frozen=True)
class Protocol:
    version: int
    shapes: Tuple[Shape, ...]
    commands: Tuple[Command, ...]
    events: Tuple[Event, ...]
    errors: Tuple[ErrorCode, ...] = field(default_factory=tuple)


def _const_name(wire_name: str) -> str:
    """`cohorts.setDataFolder` → `COHORTS_SET_DATA_FOLDER`."""
    snake = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", wire_name.replace(".", "_"))
    return snake.upper()
