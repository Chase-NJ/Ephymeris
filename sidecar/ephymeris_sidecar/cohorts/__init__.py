"""Cohort, animal, and group storage — `cohorts.md`.

Owned by the sidecar because the storage layer is sidecar-owned throughout this
project (§3). The database file lives in the app's own data directory, *not* the
user-configured `dataDirectory` — that setting is for browsable session output,
and an opaque `.db` alongside it would confuse rather than help.
"""
