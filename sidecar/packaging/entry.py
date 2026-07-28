"""PyInstaller entry point.

PyInstaller traces imports from a script, not from a `-m` module invocation,
so this shim is the frozen equivalent of `python -m ephymeris_sidecar`. It
must stay behavior-identical to `__main__` — the Tauri shell treats the frozen
binary and the dev interpreter as interchangeable.
"""

from ephymeris_sidecar.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
