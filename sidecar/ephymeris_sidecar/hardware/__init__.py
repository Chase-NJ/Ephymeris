"""The rig's own wiring: which pin each channel is on, and what it means.

Sidecar-side, under the app data dir, following `specs/store.py` exactly — the
one precedent this codebase has for a user-editable file the sidecar owns and
validates. Not a setting: settings are shell-owned, leniently parsed and
silently defaulting, which is right for a directory path and catastrophic for a
pin number.
"""
