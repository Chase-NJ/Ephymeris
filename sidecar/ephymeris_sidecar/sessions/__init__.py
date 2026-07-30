"""Session prefixes, session records, and the live session runner.

`data.md` defines what gets written and where; `dashboard.md §7`
defines what triggers the writing. Prefix/Session/SessionAnimalRun records live
in the same SQLite database as cohorts (`cohorts.md` §3); the actual per-strobe
file writing is handled by `writer.py`, not the database.
"""
