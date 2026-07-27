"""Suite-wide test configuration.

Turns on wire-shape validation (`protocol.wire_validation_enabled`) for every
test: any event built via `protocol.event()` — the runner, backup manager, and
analytics service all go through it — and any command reply dispatched through
`SidecarServer` is checked against `protocol/schema.py` and fails loudly on
drift. Production leaves this off, so a benign schema lag can never take down
a live session.
"""

from __future__ import annotations

import os

os.environ.setdefault("EPHYMERIS_WIRE_VALIDATE", "1")
