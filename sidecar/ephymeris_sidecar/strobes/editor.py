"""The strobe vocabulary editor: what the Strobes page asks of this machine's
vocabulary (`TASKS.md#strobe-vocabulary`).

`store.py` holds the rules and `usage.py` the evidence they are judged
against; this is where the two meet the rig. Every edit is a rig definition
write (`TASKS.md#the-rig-definition`): it rebuilds the same generated folders a
wiring change does, so it goes through `RigDefinition.edit_vocabulary`.

Every refusal is a `StrobeRefused` whose `reason` names the rule, or the rig
definition's `VocabularyInUse`. Neither knows the wire: `wire_errors.py` maps
them.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from .. import discovery
from ..protocol import Evt, event
from ..rig import definition as rig_definition
from ..rig import registry
from . import store as strobe_store
from .store import StrobeRefused
from .usage import ArchiveScanner, firmware_refs


class VocabularyEditor:
    def __init__(
        self,
        *,
        rig: rig_definition.RigDefinition,
        tasks: Any,
        scanner: ArchiveScanner,
        archive_roots: Callable[[], list[str]],
        broadcast: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._rig = rig
        self._tasks = tasks
        self._scanner = scanner
        self._archive_roots = archive_roots
        self._broadcast = broadcast

    # -- reads --------------------------------------------------------------- #

    async def vocabulary(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._rig.vocabulary_payload)

    async def usage(self, name: str, *, scan: bool) -> dict[str, Any]:
        """Where `name` is used, and what would refuse retiring or removing it.
        `scan` adds the archive, which can take minutes on a cold cache."""
        name = _code_name(name)
        # Reads the generated folders (`firmware_refs` over the task store).
        async with self._rig.reading():
            usage = await asyncio.to_thread(self._impact, name)
        if scan:
            index = await self._scan_archive()
            sessions = index.usage_of(usage["code"])
            usage["sessions"] = sessions
            if sessions["count"] and usage["removeBlocker"] is None:
                usage["removeBlocker"] = (
                    f"{name} is in {sessions['count']} recorded "
                    f"session{'' if sessions['count'] == 1 else 's'}; retire it instead."
                )
        return usage

    async def export(self) -> dict[str, Any]:
        doc = await asyncio.to_thread(self._rig.load_vocabulary_strict)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return {
            "document": strobe_store.export_document(doc),
            "filename": f"strobe-vocabulary-{stamp}.json",
        }

    # -- edits --------------------------------------------------------------- #

    async def add(self, name: str, code: int, *, rationale: str, emitted_on: str) -> dict[str, Any]:
        name = _code_name(name)
        return await self._edit(
            lambda doc: strobe_store.add(doc, name, code, rationale=rationale, emitted_on=emitted_on)
        )

    async def edit(self, name: str, *, rationale: str, emitted_on: str) -> dict[str, Any]:
        name = _code_name(name)
        return await self._edit(
            lambda doc: strobe_store.edit(doc, name, rationale=rationale, emitted_on=emitted_on)
        )

    async def retire(self, name: str, *, confirm: bool) -> dict[str, Any]:
        name = _code_name(name)

        def check(usage: dict[str, Any]) -> None:
            _refuse_unconfirmed(usage, confirm, "Retiring")

        return await self._edit(lambda doc: strobe_store.retire(doc, name), name=name, check=check)

    async def reinstate(self, name: str) -> dict[str, Any]:
        name = _code_name(name)
        return await self._edit(lambda doc: strobe_store.reinstate(doc, name))

    async def remove(self, name: str, *, confirm: bool) -> dict[str, Any]:
        name = _code_name(name)
        # Refused before the scan as well as inside the write: the scan can take
        # minutes on a cold cache over a share. It runs outside the write so it
        # never holds up a flash; it is re-checked against the document inside
        # the write by code, and a file recorded in the gap is the one race
        # left -- which is why a session set up or a box running refuses every
        # edit outright.
        self._rig.refuse_if_in_use(rig_definition.VocabularyInUse, rig_definition.VOCABULARY_IN_USE)
        index = await self._scan_archive()

        def check(usage: dict[str, Any]) -> None:
            sessions = index.usage_of(usage["code"])
            if sessions["count"]:
                raise StrobeRefused(
                    "in_recorded_session",
                    f"{name} is in {sessions['count']} recorded "
                    f"session{'' if sessions['count'] == 1 else 's'}, so its number can "
                    "never be reissued. Retire it instead.",
                    sessions,
                )
            _refuse_unconfirmed(usage, confirm, "Removing")

        return await self._edit(
            lambda doc: strobe_store.remove(
                doc, name, sessions_containing=index.count(_code_in(doc, name))
            ),
            name=name,
            check=check,
        )

    async def import_(self, other: Any, *, apply: bool) -> dict[str, Any]:
        """The merge plan for `other`; applied too when `apply`."""
        if not isinstance(other, dict):
            raise StrobeRefused("invalid", "That file is not a strobe vocabulary.")
        if len(json.dumps(other).encode()) > strobe_store.MAX_VOCAB_BYTES:
            raise StrobeRefused("invalid", "That file is too large to be a vocabulary.")
        doc = await asyncio.to_thread(self._rig.load_vocabulary_strict)
        plan = strobe_store.plan_merge(doc, other)
        if not apply:
            return {"plan": plan.to_json(), "vocabulary": None}
        vocabulary = await self._edit(
            lambda current: strobe_store.apply_merge(
                current, other, strobe_store.plan_merge(current, other)
            )
        )
        return {"plan": plan.to_json(), "vocabulary": vocabulary}

    # -- internals ------------------------------------------------------------ #

    async def _edit(
        self,
        edit: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        name: str | None = None,
        check: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """A vocabulary edit, as a rig definition write. `check` sees the code's
        usage inside the write, so a task saved a moment after the page last
        looked is still counted."""
        judge = None
        if name is not None and check is not None:
            def judge() -> None:
                check(self._impact(name))
        return await self._rig.edit_vocabulary(edit, check=judge)

    def _impact(self, name: str) -> dict[str, Any]:
        """`StrobeUsage` minus the archive: firmware, slots, tasks it would break.

        The task half is `impact_of`'s method with a vocabulary in place of a
        wiring: every saved task validated with and without the code, and only
        what is NEWLY broken reported.
        """
        vocab = registry.vocabulary()
        live = vocab.get(name)
        retired = vocab.retired_entry(name)
        if live is None and retired is None:
            raise StrobeRefused("invalid", f"{name} is not in the strobe vocabulary.")
        code = live.code if live is not None else retired.code

        library_root, _source = discovery.library_root()
        refs = firmware_refs([
            (library_root, "sketch"),
            (self._tasks.root, "task"),
        ]).get(name, [])
        slot = vocab.slot_of(name)

        breaks: list[dict[str, Any]] = []
        if live is not None:
            doc = self._rig.load_vocabulary_strict()
            try:
                hypothetical = strobe_store.retire(doc, name)
            except StrobeRefused:
                hypothetical = None
            if hypothetical is not None:
                breaks = rig_definition.impact_of(self._tasks, vocabulary=hypothetical)

        blocker: str | None = None
        if slot is not None:
            blocker = (
                f"{name} is how a response port on slot {slot} reports; a port with "
                "a missing code records nothing, silently."
            )
        elif any(r.kind == "library" for r in refs):
            blocker = (
                f"the shared firmware library emits BF_{name}, so every sketch would "
                "stop compiling. Remove it from the library first."
            )
        return {
            "name": name,
            "code": code,
            "status": "live" if live is not None else "retired",
            "firmware": [r.to_json() for r in refs],
            "portSlot": slot,
            "breaks": breaks,
            "sessions": None,
            "retireBlocker": blocker if live is not None else f"{name} is already retired.",
            "removeBlocker": blocker,
        }

    async def _scan_archive(self):  # noqa: ANN202
        """Every recorded file this machine can reach, reduced to code sets.

        Off the loop, progress broadcast every few dozen files so a cold scan
        over a share reads as working rather than hung.
        """
        loop = asyncio.get_running_loop()

        def progress(done: int, total: int) -> None:
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(
                    self._broadcast(
                        event(Evt.STROBES_SCAN_PROGRESS, {"done": done, "total": total})
                    )
                )
            )

        return await asyncio.to_thread(self._scanner.scan, self._archive_roots(), progress)


def _code_name(name: str) -> str:
    if not name.strip():
        raise StrobeRefused("invalid", "`name` must be a code name.")
    return name.strip()


def _refuse_unconfirmed(usage: dict[str, Any], confirm: bool, verb: str) -> None:
    name = usage["name"]
    blocker = usage["retireBlocker"] if verb == "Retiring" else usage["removeBlocker"]
    if blocker is not None:
        raise StrobeRefused("required", f"{verb} {name} is refused: {blocker}")
    named_by = usage["breaks"] or usage["firmware"]
    if named_by and not confirm:
        raise StrobeRefused(
            "would_break_tasks",
            f"{verb} {name} would stop firmware that names it compiling.",
            {"breaks": usage["breaks"], "firmware": usage["firmware"]},
        )


def _code_in(doc: dict[str, Any], name: str) -> int:
    entry = doc.get("codes", {}).get(name) or doc.get("retired", {}).get(name) or {}
    return int(entry.get("code", -1))
