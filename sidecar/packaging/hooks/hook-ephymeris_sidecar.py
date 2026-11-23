"""Every module of the sidecar goes into the frozen app, except its tests.

A feature's tests live inside its package (`<feature>/tests/`), where a plain
`--collect-submodules ephymeris_sidecar` would find them and bring pytest and
the suite's fixtures in with them. `scripts/package-resources.mjs` names this
folder with `--additional-hooks-dir`.
"""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules(
    "ephymeris_sidecar", filter=lambda name: ".tests" not in name
)
