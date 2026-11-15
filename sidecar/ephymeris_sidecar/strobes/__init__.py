"""The strobe vocabulary this machine owns — `TASKS.md#strobe-vocabulary`.

Two halves, kept apart for the same reason `hardware/` keeps the rig document
apart from the registries that compose it:

  * `store.py` — the document: `<data_dir>/strobes/vocabulary.json`, seeded once
    from the shipped default, and every edit to it (add, edit meaning, retire,
    reinstate, remove, import). Pure document operations; nothing here scans.
  * `usage.py` — the evidence an edit is judged against: which firmware names a
    code, and which recorded session contains it.

`rig/registry.py`'s `vocabulary()` is the read side. Nothing else holds a code.
"""
