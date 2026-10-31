"""Where a rig's task profiles live, and how they become flashable sketches.

Layout, under the sidecar's own data dir (beside `ephymeris.db` and
`hardware/` — sidecar-side writes, no Tauri fs capability involved):

    <data_dir>/tasks/
        <id>.json                 the DEFINITION -- the operator's document
        <category>/<name>/        the GENERATED sketch folder
            <name>.ino
            TaskPins.h
            TaskTrials.h
            task.json

THE TWO HALVES ARE KEPT APART ON PURPOSE. The definition is authored and is the
only thing worth preserving; the sketch folder is a build output, rewritten
whole on every save and again on every wiring change. Storing them together
would make "regenerate everything" indistinguishable from "delete the user's
work".

WHY THE SKETCH FOLDER IS SHAPED LIKE THE BUNDLE'S. Because `discovery.py` scans
this root as a second library, a saved profile *is* a discovered sketch — so
flashing, the session flow, `tasks.getProfile`, `settings.taskDefaults` and
Analytics all work on it with no special case anywhere. `TASKS.md#library-roots`
sanctions this as the walk-back from a single bundled library: a hidden
additional library that APPENDS to the bundle, never a return of the configured
root.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import generate
from .model import ID_RE, TaskDefinition, TaskDefinitionError
from .validate import validate

log = logging.getLogger(__name__)

#: Refuse before parsing. A definition is a few kilobytes; a megabyte of JSON is
#: not one, and the schema validator is recursive enough to make one expensive.
MAX_DEFINITION_BYTES = 256 * 1024

#: The bundled sketch a generated profile is built from. Copied rather than
#: templated: one trial runner and one session loop in the world.
ROOT_SKETCH_NAME = "GRGL"


@dataclass(frozen=True)
class TaskEntry:
    id: str
    name: str
    category: str
    path: str
    edited_at: str | None
    problems: int
    #: What the task IS, at card resolution. Counts rather than the arrays: the
    #: landing draws one tile per task and `tasks.list` is answered on every
    #: route mount, so a tile that had to open the definition to letter itself
    #: would cost a round trip each.
    trials: int
    stages: int
    selection_mode: str

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "path": self.path,
            "editedAt": self.edited_at,
            "problems": self.problems,
            "trials": self.trials,
            "stages": self.stages,
            "selectionMode": self.selection_mode,
        }


class TaskStore:
    """Reads and writes `<data_dir>/tasks/`.

    Owns the files and the regeneration, and nothing else. It must not import
    the app or the port manager: a broken definition is a diagnostic, not an
    import error.
    """

    def __init__(self, data_dir: Path, library_root: Path | None = None) -> None:
        self.root = Path(data_dir) / "tasks"
        #: Where `GRGL.ino` is read from. Injected rather than resolved here so
        #: a test can point it at a fixture without an installed library.
        self._library_root = library_root

    # -- reading ----------------------------------------------------------- #

    def definition_path(self, task_id: str) -> Path:
        return self.root / f"{task_id}.json"

    def sketch_dir(self, definition: TaskDefinition) -> Path:
        """The generated folder, which every save deletes and rewrites, so it
        must sit inside the task library. Parsing refuses a category or name
        that is not one folder name; this refuses whatever got past it, a
        definition built in code included (`TaskDefinitionError`)."""
        return self._inside(self.root / definition.category / definition.name)

    def is_stored(self, task_id: str) -> bool:
        """A file is stored under this id, whether or not it reads."""
        return bool(ID_RE.match(task_id)) and self.definition_path(task_id).is_file()

    def get(self, task_id: str) -> TaskDefinition | None:
        """The definition, or None when there is no such task.

        A file that will not parse is reported as None with a logged warning
        rather than raised: one broken document must not make the whole library
        unlistable, which is the same reasoning `hardware/store.py` applies.
        """
        document = self.document(task_id)
        if document is None:
            return None
        try:
            return TaskDefinition.from_json(document)
        except TaskDefinitionError as exc:
            log.warning("task definition %s will not parse (%s)", task_id, exc)
            return None

    def document(self, task_id: str) -> Any | None:
        """The stored `<id>.json` as JSON, verbatim, or None when there is no
        such file or it will not read. Never passed through `TaskDefinition`,
        which drops what this build does not know: a task export carries this
        (TASKS.md#moving-a-task-between-machines). An id that is not an id
        names no file: `..` would read outside the library."""
        if not ID_RE.match(task_id):
            return None
        path = self.definition_path(task_id)
        if not path.is_file():
            return None
        try:
            raw = path.read_bytes()
        except OSError as exc:
            log.warning("task definition %s unreadable (%s)", task_id, exc)
            return None
        if len(raw) > MAX_DEFINITION_BYTES:
            log.warning("task definition %s is %d bytes, over the limit", task_id, len(raw))
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning("task definition %s will not parse (%s)", task_id, exc)
            return None

    def list_definitions(self) -> list[TaskDefinition]:
        if not self.root.is_dir():
            return []
        out: list[TaskDefinition] = []
        for path in sorted(self.root.glob("*.json")):
            definition = self.get(path.stem)
            if definition is not None:
                out.append(definition)
        return out

    def list_entries(self) -> list[dict[str, Any]]:
        """Summaries for the profile list, and the shape the rig definition's
        impact check (`rig/definition.py::impact_of`) reads.

        `problems` is a COUNT rather than the diagnostics: the list is drawn on
        every route mount and validating each definition in full is cheap, but
        shipping every message would make the reply grow with the library.
        """
        out: list[dict[str, Any]] = []
        for definition in self.list_definitions():
            path = self.definition_path(definition.id)
            try:
                edited = datetime.fromtimestamp(path.stat().st_mtime, UTC)
                edited_at = edited.strftime("%Y-%m-%dT%H:%M:%SZ")
            except OSError:
                edited_at = None
            out.append(
                TaskEntry(
                    id=definition.id,
                    name=definition.name,
                    category=definition.category,
                    path=str(self.sketch_dir(definition)),
                    edited_at=edited_at,
                    problems=len(validate(definition)),
                    trials=definition.trial_count,
                    stages=definition.stage_count,
                    selection_mode=definition.selection_mode,
                    # `label` is what the impact check renders; the name is it.
                ).to_json()
                | {"label": definition.name}
            )
        return out

    def failures(self, task_id: str) -> set[str]:
        """The rule codes this profile trips right now, or an empty set.

        Read by `rig/definition.py::impact_of` under a HYPOTHETICAL rig
        definition, so it must consult the registries live rather than anything
        cached — that difference is the whole mechanism by which an edit's cost
        is computed before the write.

        A definition that will not even parse is not a wiring fault, and
        reporting it as one would make every rig edit look destructive on a rig
        with one broken task.
        """
        definition = self.get(task_id)
        if definition is None:
            return set()
        return {d.code for d in validate(definition)}

    # -- writing ----------------------------------------------------------- #

    def save(self, definition: TaskDefinition) -> list[dict[str, Any]]:
        """Write the definition, regenerate its sketch, return the diagnostics.

        ALWAYS SAVES, even with errors. A half-finished task must be savable —
        an operator interrupted mid-edit should not lose the work, and the gate
        is flashing, not saving. The generated sketch is written regardless for
        the same reason it is regenerated on a wiring change: leaving a stale
        one behind would mean the folder on disk described a task nobody has.
        """
        # Read the PREVIOUS definition before overwriting it: a rename moves the
        # generated folder, and its old location is only knowable from what was
        # stored a moment ago.
        previous = self.get(definition.id)
        self.sketch_dir(definition)  # refused before anything is written

        self._write(definition.id, definition.to_json())
        self.regenerate(definition, previous)
        return [d.to_json() for d in validate(definition)]

    def save_document(self, document: dict[str, Any]) -> list[dict[str, Any]]:
        """`save`, writing `document` itself rather than the model's
        re-serialisation of it: an imported task keeps every field, those this
        build's model does not know included
        (TASKS.md#moving-a-task-between-machines). The folder is generated
        from the parsed model, as for any save. Raises `TaskDefinitionError`
        for a document that is not a definition, before writing anything."""
        definition = TaskDefinition.from_json(document)
        previous = self.get(definition.id)
        self.sketch_dir(definition)  # refused before anything is written
        self._write(definition.id, document)
        self.regenerate(definition, previous)
        return [d.to_json() for d in validate(definition)]

    def _write(self, task_id: str, document: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.definition_path(task_id).write_text(
            json.dumps(document, indent=2) + "\n", encoding="utf-8"
        )

    def delete(self, task_id: str) -> bool:
        """Remove the definition and its generated sketch. Idempotent. An id
        that is not an id removes nothing."""
        if not ID_RE.match(task_id):
            return False
        definition = self.get(task_id)
        self.definition_path(task_id).unlink(missing_ok=True)
        if definition is not None:
            shutil.rmtree(self.sketch_dir(definition), ignore_errors=True)
            self._prune_category(definition.category)
        return definition is not None

    def regenerate(
        self, definition: TaskDefinition, previous: TaskDefinition | None = None
    ) -> Path | None:
        """Rewrite one profile's sketch folder from the current wiring.

        Returns the folder, or None when the root sketch cannot be read — in
        which case the profile is still stored and simply has nothing to flash
        yet, which is a better outcome than refusing the save.

        THE FOLDER IS REPLACED, NOT PATCHED. A renamed task leaves its old
        folder behind otherwise, and discovery would offer both.
        """
        # A spine task copies no root sketch: its runner is the library's
        # BoxSpine.h and the generator writes its few-line `.ino`.
        source = "" if definition.spine is not None else self._root_sketch_source()
        if source is None:
            log.warning(
                "no %s sketch in the bundled library; %s has no flashable sketch",
                ROOT_SKETCH_NAME,
                definition.id,
            )
            return None

        target = self.sketch_dir(definition)
        self._forget_previous_folder(definition, previous)
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)
        for name, text in generate.generated_files(definition, source).items():
            (target / name).write_text(text, encoding="utf-8")
        return target

    def regenerate_all(self) -> int:
        """Rewrite every stored profile. Called after a wiring or vocabulary change.

        Pin numbers and strobe codes are compiled into `TaskPins.h`, so a saved
        profile whose folder was generated under the old wiring would flash the
        old pins — silently, since it still compiles. This is what stops that.
        """
        count = 0
        for definition in self.list_definitions():
            if self.regenerate(definition) is not None:
                count += 1
        return count

    # -- internals ---------------------------------------------------------- #

    def _root_sketch_source(self) -> str | None:
        root = self._library_root
        if root is None:
            from .. import discovery

            found, _ = discovery.library_root()
            root = found
        if root is None:
            return None
        for candidate in Path(root).rglob(f"{ROOT_SKETCH_NAME}/{ROOT_SKETCH_NAME}.ino"):
            try:
                return candidate.read_text(encoding="utf-8")
            except OSError:
                return None
        return None

    def _forget_previous_folder(
        self, definition: TaskDefinition, previous: TaskDefinition | None
    ) -> None:
        """Drop the folder this definition owned before a rename or re-category.

        Renaming a task is an ordinary edit, and without this the previous
        folder stays on disk — so discovery offers TWO sketches for one task and
        flashing the wrong one is a silent mistake.

        Keyed on the PREVIOUS definition rather than on a scan of the tree,
        because a folder cannot be attributed to a task from its contents: the
        generated `task.json` carries the task's NAME, which is precisely the
        thing that just changed. Scanning for a match would either miss every
        rename or delete a different task's folder that happened to look alike.
        """
        if previous is None:
            return
        stale = self.sketch_dir(previous)
        if stale == self.sketch_dir(definition):
            return
        shutil.rmtree(stale, ignore_errors=True)
        self._prune_category(previous.category)

    def _inside(self, path: Path) -> Path:
        root = self.root.resolve()
        resolved = path.resolve()
        if resolved == root or not resolved.is_relative_to(root):
            raise TaskDefinitionError(
                f"{path} is outside the task library {self.root}; nothing was written there."
            )
        return path

    def _prune_category(self, category: str) -> None:
        folder = self.root / category
        try:
            self._inside(folder)
        except TaskDefinitionError:
            return
        try:
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
        except OSError:
            pass
