"""Per-animal session file writer — `data.md` §4, §7.

The `.tsv` is the **write-ahead log** that makes the durability guarantee real
(§7), not a redundant export. Every strobe is appended and `flush()` +
`fsync()`'d the instant it arrives, in the exact `<code>\t<timestamp>` form the
board sends — no transformation, so a formatting bug can't corrupt the one file
that has to be bulletproof. `.json` and `.mat` are built once at clean
finalization from the same in-memory list the `.tsv` was fed from.

Per-line fsync is safe here because the real session rate is well under one event
per second (§7.1); a few-ms fsync per line is nowhere near a bottleneck.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from . import matwriter

log = logging.getLogger(__name__)


class WriteError(Exception):
    """A `.tsv` write failed mid-session (disk full, permissions)."""


class AnimalWriter:
    """Owns one animal's three output files for the life of its run.

    Lifecycle: ``open_files`` → ``record`` (many) → ``finalize``. The header is
    written by ``open_files`` because everything it needs (rat, port, config) is
    known before the first strobe; the footer waits for ``finalize`` since
    `stop_reason`/`n_events` aren't known until then.
    """

    def __init__(
        self,
        tsv_path: Path,
        json_path: Path,
        mat_path: Path,
        core_metadata: dict[str, Any],
        config_metadata: dict[str, Any],
    ) -> None:
        self._tsv_path = tsv_path
        self._json_path = json_path
        self._mat_path = mat_path
        # Core fields (rat, serial_port, session_id, sketch) + task-profile
        # config fields, merged flat at the top level to match the sample (§5).
        self._core = dict(core_metadata)
        self._config = dict(config_metadata)
        self._events: list[list[int]] = []
        self._tsv = None  # type: Any
        self._finalized = False
        self._stop_reason: str | None = None

    # --- setup ------------------------------------------------------------

    def open_files(self) -> None:
        """Create the folders, open the `.tsv`, and write its header.

        Called after `START`/`SEED` resolve, before the first strobe (§7.1).

        Opened **exclusively** (`"x"`), not truncating. The `HHMMSS` in the
        filename (§2) already makes a collision practically unreachable, so
        this will effectively never fire — but this is the one file carrying
        the durability guarantee, and "practically unreachable" is a weaker
        claim there than anywhere else. Refusing to start beats silently
        overwriting a previous animal's data.
        """
        for path in (self._tsv_path, self._json_path, self._mat_path):
            path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._tsv = open(self._tsv_path, "x", encoding="utf-8", newline="\n")
        except FileExistsError as exc:
            raise WriteError(
                f"{self._tsv_path} already exists — refusing to overwrite a "
                f"session file. Move or rename it, then start this box again."
            ) from exc
        except OSError as exc:
            raise WriteError(f"couldn't open {self._tsv_path}: {exc}") from exc

        # `# key: value` header comment lines — core fields then config fields.
        for key, value in {**self._core, **self._config}.items():
            self._tsv.write(f"# {key}: {_render(value)}\n")
        self._flush()

    # --- per-strobe -------------------------------------------------------

    def record(self, code: int, timestamp: int) -> None:
        """Append one strobe to memory and to the `.tsv`, fsync'd (§7.1)."""
        if self._finalized:
            return
        self._events.append([code, timestamp])
        try:
            # Exactly the board's own line format — no transformation.
            self._tsv.write(f"{code}\t{timestamp}\n")
            self._flush()
        except OSError as exc:
            raise WriteError(f"write to {self._tsv_path} failed: {exc}") from exc

    # --- teardown ---------------------------------------------------------

    def finalize(self, stop_reason: str) -> dict[str, Any]:
        """Append the `.tsv` footer, then build `.json` and `.mat` once (§7.2).

        Returns the finished document (also the in-memory source for both
        structured formats), so callers don't re-read it off disk. Idempotent:
        the first `stop_reason` wins, so a redundant call (e.g. a board-drop
        finalize racing an operator stop) can't rewrite the recorded reason.
        """
        if self._finalized:
            return self._document(self._stop_reason or stop_reason)
        self._finalized = True
        self._stop_reason = stop_reason

        document = self._document(stop_reason)

        # Footer: the two fields not knowable at header time (§7.1).
        if self._tsv is not None:
            try:
                self._tsv.write(f"# stop_reason: {stop_reason}\n")
                self._tsv.write(f"# n_events: {len(self._events)}\n")
                self._flush()
            finally:
                self._tsv.close()
                self._tsv = None

        # Structured formats, built once from the same list (§7.2). A failure
        # here doesn't cost data — the .tsv already holds everything durably.
        try:
            self._json_path.write_text(
                json.dumps(document, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            log.error("couldn't write %s: %s", self._json_path, exc)
        try:
            matwriter.savemat(str(self._mat_path), document)
        except OSError as exc:
            log.error("couldn't write %s: %s", self._mat_path, exc)

        return document

    # --- internals --------------------------------------------------------

    def _document(self, stop_reason: str) -> dict[str, Any]:
        """The full per-animal document (§5). Core, then flat config, then data."""
        doc: dict[str, Any] = dict(self._core)
        doc.update(self._config)
        doc["stop_reason"] = stop_reason
        doc["n_events"] = len(self._events)
        doc["ts_data"] = [list(pair) for pair in self._events]
        return doc

    def _flush(self) -> None:
        assert self._tsv is not None
        self._tsv.flush()
        os.fsync(self._tsv.fileno())

    @property
    def event_count(self) -> int:
        return len(self._events)


def _render(value: Any) -> str:
    """Header-comment rendering — bools as lowercase, matching the JSON body."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
