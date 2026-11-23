"""Compiling the task simulator, and finding the one that was compiled.

The simulator is `host/tasksim.cpp`, beside this file:
the bundled `GRGL.ino` and `BehaviorBox.h` on the instrumented host shim, one
executable per selection mode because the sketch picks its selector with `#if`.

An installed app ships them (`scripts/package-resources.mjs` runs this module)
and the shell names their folder in `EPHYMERIS_BUNDLED_TASK_SIM`. A source
checkout compiles them on first use into `sidecar/build/tasksim`, and again
whenever a source is newer than the executables.

    python -m ephymeris_sidecar.simulation --out DIR

Run that way it also runs each simulator through one trial (`check`), so an
installer is never staged with one that compiled and does not run. On Windows
the compiler is MinGW's `g++`, linked statically: the lab PCs have no runtime
for it to find.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from .. import discovery

BUNDLED_ENV = "EPHYMERIS_BUNDLED_TASK_SIM"

MODES = {"antibias": 0, "pool": 1, "weighted": 2}

COMPILERS = ("g++", "c++", "clang++") if os.name == "nt" else ("c++", "clang++", "g++")

_SKETCH = Path("Olfactory Behavior") / "GRGL" / "GRGL.ino"
_LIBRARY = Path("libraries") / "BehaviorBox"
_SHIM = _LIBRARY / "extras" / "host_test"
HARNESS = Path(__file__).resolve().parent / "host"
_HARNESS_FILES = ("tasksim.cpp", "TaskPins.h", "TaskTrials.h")

_building = threading.Lock()


class SimulatorUnavailable(Exception):
    """This computer has no task simulator and cannot compile one."""


def executable(directory: Path, mode: str) -> Path:
    return directory / f"tasksim-{mode}{'.exe' if os.name == 'nt' else ''}"


def sources(firmware: Path) -> list[Path]:
    """Every file a simulator is compiled from."""
    return [
        firmware / _SKETCH,
        firmware / _LIBRARY / "BehaviorBox.h",
        firmware / _LIBRARY / "BoxPins.h",
        firmware / _LIBRARY / "BoxStrobes.h",
        firmware / _SHIM / "box_shim" / "Arduino.h",
        *(HARNESS / name for name in _HARNESS_FILES),
    ]


def compiler() -> str | None:
    named = os.environ.get("CXX")
    if named and shutil.which(named):
        return named
    return next((found for found in map(shutil.which, COMPILERS) if found), None)


def build(out_dir: Path, firmware: Path, cxx: str | None = None) -> None:
    """Compile the three simulators into `out_dir`.

    The sketch is copied beside the simulator's own `TaskPins.h` and
    `TaskTrials.h`, as a generated task's folder holds it: its quoted includes
    resolve next to it, and the bundled folder's two default headers must lose.
    """
    cxx = cxx or compiler()
    if cxx is None:
        raise SimulatorUnavailable(
            "Simulating a task compiles its firmware for this computer, and no C++ "
            f"compiler was found ({', '.join(COMPILERS)})."
        )
    missing = [str(path) for path in sources(firmware) if not path.is_file()]
    if missing:
        raise SimulatorUnavailable(f"The simulator's sources are missing: {', '.join(missing)}.")

    staging = out_dir / "src"
    staging.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(firmware / _SKETCH, staging / "GRGL.ino")
    for name in _HARNESS_FILES:
        shutil.copyfile(HARNESS / name, staging / name)

    windows = os.name == "nt"
    for mode, number in MODES.items():
        command = [
            cxx, "-std=c++14" if windows else "-std=c++11", "-O2", "-Wall", "-Wno-unused-function",
            "-DBB_AVR_RANDOM", f"-DBBSIM_SELECTION_MODE={number}",
            f"-I{staging}", f"-I{firmware / _SHIM / 'box_shim'}", f"-I{firmware / _SHIM}",
            f"-I{firmware / _LIBRARY}",
            "-x", "c++", str(staging / "tasksim.cpp"), "-o", str(executable(out_dir, mode)),
        ]
        if windows:
            command.insert(1, "-static")
        built = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        if built.returncode != 0:
            raise SimulatorUnavailable(
                f"The task simulator did not compile ({mode}):\n{built.stdout}{built.stderr}"
            )


def check(directory: Path) -> None:
    """Run each simulator in `directory` through a session of one trial nobody
    answers, stopped at once: the table, the start, the outputs and the end."""
    from ..rig import registry

    vocab = registry.vocabulary()
    row = "ROW 1 0 R 0 {} {} {} 100 {}".format(
        *(vocab.code_of(name) for name in ("ODOR_1_ON", "FLUID_R", "STOP_FLUID_G_R", "TRIAL_TYPE_1"))
    )
    table = [f"CODE {entry.name} {entry.code}" for entry in vocab]
    table += [row, "STOP_AT 1", "LIMIT 600000", "END", "START SEED=1"]
    for mode in MODES:
        path = executable(directory, mode)
        process = subprocess.Popen([str(path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   text=True, encoding="utf-8")
        overdue = threading.Timer(30.0, process.kill)
        overdue.start()
        heard: list[str] = []
        try:
            process.stdin.write("".join(f"{line}\n" for line in table))
            process.stdin.flush()
            for line in process.stdout:
                heard.append(line.strip())
                if line.startswith("@END") or line.startswith("@ABORT"):
                    break
                if line.startswith("@ "):
                    process.stdin.write(".\n")
                    process.stdin.flush()
        except OSError:
            pass
        finally:
            overdue.cancel()
            process.kill()
            process.wait()
        strobed = {line.split("\t")[0] for line in heard if "\t" in line}
        wanted = {f"{vocab.code_of(name):03d}" for name in ("START_SESSION", "LAZY_RAT", "END_SESSION")}
        if "READY" not in heard or heard[-1:] != ["@END"] or not wanted <= strobed:
            raise SimulatorUnavailable(
                f"The task simulator at {path} did not run a trial: {' | '.join(heard[-6:]) or 'no output'}."
            )


def _checkout_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "build" / "tasksim"


def _stale(directory: Path, firmware: Path) -> bool:
    built = [executable(directory, mode) for mode in MODES]
    if not all(path.is_file() for path in built):
        return True
    oldest = min(path.stat().st_mtime for path in built)
    return any(path.stat().st_mtime > oldest for path in sources(firmware) if path.is_file())


def locate(mode: str) -> Path:
    """The simulator for `mode`, compiled first when a checkout's is missing or old."""
    if mode not in MODES:
        raise SimulatorUnavailable(f"No simulator is built for selection mode {mode!r}.")
    bundled = os.environ.get(BUNDLED_ENV)
    if bundled:
        found = executable(Path(bundled), mode)
        if not found.is_file():
            raise SimulatorUnavailable(f"This install's task simulator is missing: {found}.")
        return found
    if getattr(sys, "frozen", False):
        raise SimulatorUnavailable("This install was built without the task simulator.")

    firmware, _ = discovery.library_root()
    if firmware is None:
        raise SimulatorUnavailable("No firmware folder to compile the task simulator from.")
    directory = _checkout_dir()
    with _building:
        if _stale(directory, firmware):
            build(directory, firmware)
    return executable(directory, mode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile the task simulator.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--firmware", type=Path, default=None)
    args = parser.parse_args(argv)
    firmware = args.firmware or discovery.library_root()[0]
    if firmware is None:
        print("no firmware folder found", file=sys.stderr)
        return 1
    try:
        build(args.out, firmware)
        check(args.out)
    except SimulatorUnavailable as error:
        print(error, file=sys.stderr)
        return 1
    shutil.rmtree(args.out / "src", ignore_errors=True)
    print(f"task simulator built and run in {args.out}")
    return 0

