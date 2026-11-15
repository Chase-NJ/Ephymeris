"""A decode-only sketch (`TASKS.md#decode-only-sketches`): still bundled, so the
runs it recorded decode, but never offered at mapping or in Debug Mode, and
refused by the sidecar if a client names it anyway.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ephymeris_sidecar.discovery import LIBRARY_ENV, discover
from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.sketch_library import SketchLibrary
from ephymeris_sidecar.tasks import profile as task_profile
from tests.fixtures import spine as fixture
from tests.live_sidecar import Refused
from tests.wire import dispatch, running_app

FIRMWARE = Path(__file__).resolve().parents[2] / "firmware"
GRGL_SIM = FIRMWARE / "Utility" / "GRGL_Sim"


def make_sketch(root: Path, name: str, profile: object | None = None) -> Path:
    folder = root / "Tasks" / name
    folder.mkdir(parents=True)
    (folder / f"{name}.ino").write_text("void setup(){}\n", encoding="utf-8")
    if profile is not None:
        text = profile if isinstance(profile, str) else json.dumps(profile)
        (folder / "task.json").write_text(text, encoding="utf-8")
    return folder


def test_a_sketch_whose_task_json_says_so_is_decode_only(tmp_path, monkeypatch):
    monkeypatch.setenv(LIBRARY_ENV, str(tmp_path))
    make_sketch(tmp_path, "Kept", {"taskName": "Kept", "decodeOnly": True})
    make_sketch(tmp_path, "Live", {"taskName": "Live"})
    make_sketch(tmp_path, "Bare")
    make_sketch(tmp_path, "Broken", "{not json")
    found = {s["name"]: s["decodeOnly"] for s in discover().to_json()["sketches"]}
    assert found == {"Bare": False, "Broken": False, "Kept": True, "Live": False}


def test_a_rebuilt_copy_of_a_decode_only_sketch_stays_decode_only(tmp_path, monkeypatch):
    bundle, pinned = tmp_path / "bundle", tmp_path / "pinned"
    monkeypatch.setenv(LIBRARY_ENV, str(bundle))
    make_sketch(bundle, "Kept", {"taskName": "Kept", "decodeOnly": True})
    make_sketch(pinned, "Kept", {"taskName": "Kept", "decodeOnly": True})
    [sketch] = discover(pinned_root=pinned).sketches
    assert sketch.path.startswith(str(pinned)) and sketch.decode_only


def test_grgl_sim_is_the_one_decode_only_sketch_the_app_ships(monkeypatch):
    monkeypatch.setenv(LIBRARY_ENV, str(FIRMWARE))
    assert [s.name for s in discover().sketches if s.decode_only] == ["GRGL_Sim"]


def test_the_mark_leaves_the_profile_hash_alone():
    # GRGL_Sim's runs (and GRGL's, once #115 marks it) keep their history.
    raw = json.loads((GRGL_SIM / "task.json").read_text(encoding="utf-8"))
    assert raw.pop("decodeOnly") is True
    assert task_profile.profile_hash(task_profile.load_profile(str(GRGL_SIM))) == \
        task_profile.profile_hash(task_profile.parse_profile(raw, vocabulary=registry.vocabulary()))


async def test_a_run_a_decode_only_sketch_recorded_still_finds_its_profile(tmp_path, monkeypatch):
    # A run's file names its sketch; Analytics resolves it against the library
    # (`DATA.md#orphan-adoption`), decode-only or not.
    monkeypatch.setenv(LIBRARY_ENV, str(FIRMWARE))

    async def announce() -> None:
        return None

    library = SketchLibrary(tmp_path / "tasks", tmp_path / "pinned", on_rescan=announce)
    path = library.path_for_name("GRGL_Sim")
    assert path is not None and library.find(path).decode_only
    assert task_profile.load_profile(path) is not None


@pytest.fixture
def library(monkeypatch):
    monkeypatch.setenv(LIBRARY_ENV, str(FIRMWARE))


async def test_debug_mode_refuses_to_flash_a_decode_only_sketch(tmp_path, library):
    async with running_app(tmp_path / "app") as app:
        fixture.install()
        path = next(s.path for s in app.sketches.current.sketches if s.decode_only)
        with pytest.raises(Refused) as refused:
            await dispatch(app, "flash.enqueue", boxes=[1], sketchPath=path)
    assert refused.value.code == "SKETCH_DECODE_ONLY"


async def test_debug_mode_refuses_to_start_a_decode_only_sketch(tmp_path, library):
    async with running_app(tmp_path / "app") as app:
        fixture.install()
        path = next(s.path for s in app.sketches.current.sketches if s.decode_only)
        with pytest.raises(Refused) as refused:
            await dispatch(app, "port.sendStart", box=1, sketchPath=path, config={})
    assert refused.value.code == "SKETCH_DECODE_ONLY"


async def test_a_mapping_refuses_a_decode_only_sketch(tmp_path, library):
    async with running_app(tmp_path / "app") as app:
        fixture.install()
        path = next(s.path for s in app.sketches.current.sketches if s.decode_only)
        with pytest.raises(Refused) as refused:
            await dispatch(app, "sessions.confirmMapping", sessionId="s1", groupId="g1",
                           boxes=[{"box": 2, "animalId": "a1", "sketchPath": path, "config": {}}])
    assert refused.value.code == "SKETCH_DECODE_ONLY"
    assert refused.value.detail["box"] == 2
