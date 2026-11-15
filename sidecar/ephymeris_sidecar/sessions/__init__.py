"""Session prefixes, session records, and the live session runner.

`DATA.md` defines what gets written and where;
`ARCHITECTURE.md#session-lifecycle` defines what triggers the writing. Prefix/Session/SessionAnimalRun records live
in the same SQLite database as cohorts (`DATA.md#sqlite-database`); the actual per-strobe
file writing is handled by `writer.py`, not the database.
"""
