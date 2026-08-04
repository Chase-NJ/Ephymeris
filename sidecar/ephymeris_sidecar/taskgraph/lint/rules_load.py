"""TG1xx — parse and schema rules.

These run before the spec is bound, on the raw document, and they are registered
like every other rule so they appear in the rule table with help text and are
covered by the same fixture battery. A check that lives outside the registry is a
check nobody can enumerate, and enumeration is what the coverage test relies on.

Order matters here in a way it does not in later passes: TG100 short-circuits
everything (a document that will not parse has no keys to inspect), so `load()`
runs these in code order rather than by code number.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ephymeris_sidecar.taskgraph.errors import Diagnostic, Severity
from ephymeris_sidecar.taskgraph.lint import Pass, rule

from ..paths import TASK_SPEC_SCHEMA as SCHEMA_PATH


@dataclass
class LoadContext:
    """The raw document, plus whatever survived parsing."""

    text: str
    spec_id: str | None = None
    raw: dict | None = None
    parse_error: str | None = None
    source_path: str | None = None
    _schema: dict = field(default_factory=dict)

    def schema(self) -> dict:
        if not self._schema:
            self._schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        return self._schema


def _err(ctx: LoadContext, code: str, loc: str | None, msg: str, **kw) -> Diagnostic:
    return Diagnostic(
        code=code, severity=Severity.ERROR, spec_id=ctx.spec_id, location=loc, message=msg, **kw
    )


@rule(
    "TG100",
    name="unparseable",
    severity=Severity.ERROR,
    pass_=Pass.LOAD,
    help=(
        "Fix the YAML syntax error reported in the message; nothing else can be checked "
        "until the document parses."
    ),
)
def unparseable(ctx: LoadContext) -> Iterator[Diagnostic]:
    if ctx.parse_error:
        yield _err(ctx, "TG100", None, f"YAML will not parse: {ctx.parse_error}")
    elif ctx.raw is None:
        # An EMPTY document. safe_load("") returns None with no parse error, and
        # every rule below guards on isinstance(dict) and returns quietly -- so
        # without this the bag comes back clean and binding crashes on None.
        # It never surfaced from the CLI because nobody compiles an empty file;
        # an editor compiles one the moment a new spec is started.
        yield _err(ctx, "TG100", None, "the document is empty")
    elif not isinstance(ctx.raw, dict):
        yield _err(ctx, "TG100", None, "spec must be a mapping at the top level")


def _walk_keys(node: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        for k, v in node.items():
            here = f"{path}.{k}" if path else str(k)
            yield here, k
            yield from _walk_keys(v, here)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_keys(v, f"{path}[{i}]")


@rule(
    "TG101",
    name="yaml-reserved-key",
    severity=Severity.ERROR,
    pass_=Pass.LOAD,
    help=(
        'Quote the key ("on":) or rename it. Phase 0 lost the outcome trigger field to '
        "exactly this and renamed it `trigger`."
    ),
    decision="D12",
)
def yaml_reserved_key(ctx: LoadContext) -> Iterator[Diagnostic]:
    """A key YAML 1.1 silently resolved to a boolean.

    Reported as a bare True/False, because by the time PyYAML hands the document
    over the original spelling is gone. That is the whole hazard: the field does
    not look wrong, it looks absent.
    """
    if not isinstance(ctx.raw, dict):
        return
    for path, key in _walk_keys(ctx.raw):
        if isinstance(key, bool):
            yield _err(
                ctx, "TG101", path,
                f"key resolved to the boolean {key} — YAML 1.1 turns a bare "
                f"on/off/yes/no/y/n key into a boolean",
            )


@rule(
    "TG103",
    name="authored-graph",
    severity=Severity.ERROR,
    pass_=Pass.LOAD,
    help=(
        "Nodes come from a versioned epoch template. If the graph you need is not expressible in topology "
        "knobs, the fix is a new template version."
    ),
    decision="D1",
)
def authored_graph(ctx: LoadContext) -> Iterator[Diagnostic]:
    """A spec trying to author its own nodes.

    The schema's additionalProperties:false rejects these too, but its message
    ("Additional properties are not allowed") does not explain why -- and this is
    the prohibition most likely to be attempted in good faith, by someone who
    wants a node the template does not emit.
    """
    if not isinstance(ctx.raw, dict):
        return
    for key in ("nodes", "edges", "states", "graph"):
        if key in ctx.raw:
            yield _err(
                ctx, "TG103", key,
                f"`{key}` is not a spec key — nodes come from the template",
                detail=(
                    "Arbitrary graphs are not supported: the epoch model is what makes\n"
                    "compilation, validation and the eventual UI tractable."
                ),
            )


@rule(
    "TG102",
    name="schema-violation",
    severity=Severity.ERROR,
    pass_=Pass.LOAD,
    help=(
        "The spec must validate against schema/task_spec.v1.json. The message quotes the "
        "specific constraint."
    ),
)
def schema_violation(ctx: LoadContext) -> Iterator[Diagnostic]:
    if not isinstance(ctx.raw, dict):
        return
    import jsonschema

    validator = jsonschema.Draft202012Validator(ctx.schema())
    for err in sorted(validator.iter_errors(ctx.raw), key=lambda e: list(e.path)):
        yield _err(ctx, "TG102", _json_path(err.path) or "(root)", err.message)


def _json_path(path) -> str:  # noqa: ANN001 - jsonschema's deque of str|int
    """jsonschema's error path, in THIS repo's location grammar.

    A naive dot-join renders an array index as `timing.5.ms`, which is a sixth
    location spelling nothing else emits and normalize_location() cannot map to
    an overlay key -- so a schema violation on an array element would reach a
    form as a document-level banner instead of landing on its field. Brackets
    (`timing[5].ms`) are what every hand-written rule already uses.
    """
    out = ""
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out
