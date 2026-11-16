"""Intan RHX integration (`docs/RECORDING.md`).

Ephymeris drives a locally-running Intan RHX over its TCP protocol: one command
socket for get/set/execute, and RHX's two data sockets for the sync check and
the live firing map (`RECORDING.md#live-firing-map`). The
governing rule is the Backup mirror's, restated: **RHX may be slow, absent or
dead and none of that may stall or fail a behavior session.** The single
exception is *starting* a recording, which refuses before any box is started.

Stdlib only -- `asyncio` streams, `struct`, `xml.etree`. Nothing here may add a
runtime dependency (`ARCHITECTURE.md#dependency-policy`).

    client.py    the command socket: get / set / execute, with confirmation
    streams.py   pure parsers for the waveform and spike sockets
    analysis.py  pure: sync-edge matching, and the clock spike lags are timed on
    probemap.py  Intan's probe-map XML -> the JSON the probe map draws
    service.py   the long-lived subsystem `Application` owns
"""
