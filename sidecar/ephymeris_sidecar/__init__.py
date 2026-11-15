"""Ephymeris backend sidecar.

Owns all serial I/O, `arduino-cli` interaction, storage, and analytics. The
frontend reaches this process only over the local WebSocket defined in
`docs/websocket-protocol.md` — it never touches serial ports or `arduino-cli`
directly.
"""

__version__ = "0.1.0"
