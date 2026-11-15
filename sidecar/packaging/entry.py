"""PyInstaller entry point.

PyInstaller traces imports from a script, not from a `-m` module invocation,
so this shim is the frozen equivalent of `python -m ephymeris_sidecar`. It
must stay behavior-identical to `__main__` — the Tauri shell treats the frozen
binary and the dev interpreter as interchangeable.
"""

import multiprocessing

from ephymeris_sidecar.__main__ import main

if __name__ == "__main__":
    # First, before anything parses arguments: in the frozen build the live
    # scorer (`sessions/scorer.py`) is this executable started again by
    # `multiprocessing`'s spawn, and this is where it turns into the child
    # instead of a second sidecar (`ARCHITECTURE.md#the-live-scorer`).
    multiprocessing.freeze_support()
    raise SystemExit(main())
