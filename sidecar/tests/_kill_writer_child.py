"""Subprocess helper for the write-ahead-log kill test.

Opens an `AnimalWriter`, writes a fixed number of fsync'd strobe lines, touches a
"ready" sentinel, then blocks forever — so the parent can SIGKILL it at a known
point and prove the `.tsv` survived intact. Never finalizes, so no footer and no
`.json`/`.mat` should exist afterward.

Usage: python _kill_writer_child.py <tsv> <json> <mat> <n_lines> <ready_file>
"""

import sys
import time
from pathlib import Path

# Make the sidecar package importable when run as a bare script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ephymeris_sidecar.sessions.writer import AnimalWriter  # noqa: E402


def main() -> None:
    tsv, json_path, mat, n_lines, ready = sys.argv[1:6]
    writer = AnimalWriter(
        Path(tsv),
        Path(json_path),
        Path(mat),
        core_metadata={
            "rat": "remy1",
            "serial_port": "COM6",
            "session_id": "2O-Bdisc_25",
            "sketch": "GRGL_2-Odor",
        },
        config_metadata={"correction_left": 0, "lazy_escalation": True},
    )
    writer.open_files()
    for i in range(int(n_lines)):
        # Codes/timestamps mimic a real stream; each is fsync'd before the next.
        writer.record(100 + i, i * 1000)

    Path(ready).write_text("ready")
    # Block forever — the parent kills us here, mid-session, before finalize.
    while True:
        time.sleep(0.1)


if __name__ == "__main__":
    main()
