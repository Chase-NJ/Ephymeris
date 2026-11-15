"""The sketches this rig can flash, as of the last scan (`TASKS.md#sketch-library`).

`discovery.discover` walks the bundled library, the rebuilt bundled sketches
and the saved task profiles; this keeps its latest answer, is the one place
that re-asks, and resolves a recorded sketch name back to a folder.

A rescan reads the filesystem, so it runs off the event loop. It never runs
mid rig-definition write by itself: its callers hold `RigDefinition.reading()`
or are the write (`TASKS.md#the-rig-definition`).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path

from . import discovery
from .discovery import Sketch, SketchDiscovery
from .tasks import profile as task_profile

log = logging.getLogger(__name__)


class SketchLibrary:
    def __init__(
        self,
        tasks_root: Path,
        pinned_root: Path,
        *,
        on_rescan: Callable[[], Awaitable[None]],
    ) -> None:
        self._tasks_root = tasks_root
        self._pinned_root = pinned_root
        #: Told after every `rescan`, to announce the new list.
        self._on_rescan = on_rescan
        # A real scan, not a placeholder: the library ships with the app, so
        # there is no "not configured yet" to wait out -- a fresh launch either
        # has its sketches or is damaged, and both are knowable immediately.
        self._current = self._discover()
        # `legacyNames` -> sketch path, built lazily by `path_for_name` and tied
        # to the discovery it was built from. Read from an analytics worker
        # thread while a rescan runs, hence the lock.
        self._legacy_names: dict[str, str] = {}
        self._legacy_names_from: object | None = None
        self._legacy_names_lock = threading.Lock()

    @property
    def current(self) -> SketchDiscovery:
        """The latest scan's result."""
        return self._current

    def find(self, path: object) -> Sketch | None:
        """The discovered sketch at `path`. Only a discovered sketch is
        flashable or startable (`TASKS.md#sketch-library`)."""
        return next((s for s in self._current.sketches if s.path == path), None)

    def bundled_named(self, name: str) -> Sketch | None:
        return next(
            (s for s in self._current.sketches if s.source == "bundled" and s.name == name), None
        )

    def path_for_name(self, name: str) -> str | None:
        """A document's `sketch` field resolved against the library -- how an
        adopted orphan finds a `task.json` to decode with
        (`DATA.md#orphan-adoption`). First discovery-order match wins, same as
        the picker.

        Falls back to profiles that *declare* the name in `legacyNames`
        (`TASKS.md#legacy-names`), which is how a run recorded by older software
        under a human label ("Shape - L") reaches the sketch that can decode it.
        Declared, never inferred: resemblance is not evidence, and decoding
        real data with the wrong strobe map is worse than not decoding it.

        The fallback index is built on first use rather than on every rescan,
        which runs on every settings push: a directory whose legacy names
        nobody asks about should cost no reads at all. It is keyed on the
        discovery object it was built from, so a rescan invalidates it.
        """
        current = self._current
        match = next((s for s in current.sketches if s.name == name), None)
        if match is not None:
            return match.path

        with self._legacy_names_lock:
            if self._legacy_names_from is not current:
                self._legacy_names = task_profile.build_legacy_name_index(current.sketches)
                self._legacy_names_from = current
            return self._legacy_names.get(name)

    def rescan_now(self) -> None:
        """Synchronous, before the loop serves anyone: startup only."""
        self._current = self._discover()

    async def rescan(self) -> None:
        """Re-walk the library off the event loop, then announce it."""
        result = await asyncio.to_thread(self._discover)
        self._current = result
        log.info(
            "sketch library %s (%s): %d sketches, %d skipped",
            result.library.state,
            result.library.path,
            len(result.sketches),
            len(result.skipped),
        )
        await self._on_rescan()

    def _discover(self) -> SketchDiscovery:
        return discovery.discover(self._tasks_root, self._pinned_root)
