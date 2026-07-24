"""Session prefixes, session records, and the live session runner.

`data-saving.md` defines what gets written and where; `starting-a-session.md`
defines what triggers the writing. Prefix/Session/SessionAnimalRun records live
in the same SQLite database as cohorts (`cohorts.md` §3); the actual per-strobe
file writing is handled by `writer.py`, not the database.
"""
