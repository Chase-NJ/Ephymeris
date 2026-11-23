"""The packaged sidecar's check (`packaging/check_frozen.py`,
`DEVELOPING.md#building-the-installer`), run here on this interpreter's own
sidecar.

The installer build is the only place the check meets a frozen sidecar, and it
runs when a release is being made. These run the same code on every push, on
Windows too: a change to the wire or to recovery that breaks the check fails
here first, and the ways a freeze goes wrong are shown to fail it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SIDECAR_DIR = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("check_frozen", SIDECAR_DIR / "packaging" / "check_frozen.py")
check_frozen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_frozen)

SIDECAR = [sys.executable, "-m", "ephymeris_sidecar"]


def sidecar_without(module: str) -> list[str]:
    """This interpreter's sidecar, as a freeze that left `module` out runs it."""
    return [
        sys.executable, "-c",
        f"import sys; sys.modules[{module!r}] = None; "
        "from ephymeris_sidecar.__main__ import main; raise SystemExit(main())",
    ]


@pytest.fixture(autouse=True)
def a_sidecar_started_from_its_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """The child finds this tree's package wherever pytest was started, and
    starts no arduino-cli daemon on a machine that has one."""
    monkeypatch.chdir(SIDECAR_DIR)
    monkeypatch.setenv("EPHYMERIS_NO_GRPC_DAEMON", "1")


def test_a_working_sidecar_passes(tmp_path: Path) -> None:
    did = check_frozen.check(SIDECAR, tmp_path)

    assert "recovered a crashed run" in did and "exited cleanly" in did


def test_a_sidecar_that_cannot_write_a_mat_is_refused_though_it_reports_the_run_recovered(tmp_path: Path) -> None:
    with pytest.raises(check_frozen.CheckFailed, match=r"recovered the run and wrote no \S+\.mat") as refused:
        check_frozen.check(sidecar_without("scipy"), tmp_path)

    assert "scipy.io failed to import" in str(refused.value), "the sidecar's own log says why"


def test_a_sidecar_that_hangs_at_launch_is_refused_when_the_wait_runs_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_frozen, "LAUNCH_SECONDS", 1.0)

    with pytest.raises(check_frozen.CheckFailed, match="no handshake within 1 s, with stdin held open"):
        check_frozen.check([sys.executable, "-c", "import time; time.sleep(600)"], tmp_path)


def test_a_sidecar_that_dies_at_launch_is_refused(tmp_path: Path) -> None:
    with pytest.raises(check_frozen.CheckFailed, match="exited 3 before printing its handshake"):
        check_frozen.check([sys.executable, "-c", "raise SystemExit(3)"], tmp_path)


def test_an_executable_that_is_not_there_is_refused(tmp_path: Path) -> None:
    with pytest.raises(check_frozen.CheckFailed, match="would not start"):
        check_frozen.check([str(tmp_path / "ephymeris-sidecar")], tmp_path)


def test_the_command_line_exits_nonzero_on_a_refusal(capsys: pytest.CaptureFixture[str]) -> None:
    assert check_frozen.main([sys.executable, "-c", "raise SystemExit(3)"]) == 1
    assert "the packaged sidecar failed its check" in capsys.readouterr().err
    assert check_frozen.main(SIDECAR) == 0
