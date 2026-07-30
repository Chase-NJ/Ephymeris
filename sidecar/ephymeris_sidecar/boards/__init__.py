"""Board tooling: discovery and flashing via arduino-cli."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .tool import BoardTool

log = logging.getLogger(__name__)

#: Escape hatch for lab troubleshooting: force the subprocess backend even
#: when grpcio imports fine. Documented in `README.md` §4.1.
NO_DAEMON_ENV = "EPHYMERIS_NO_GRPC_DAEMON"


def create_board_tool(app_data_dir: Path | None = None) -> BoardTool:
    """The gRPC daemon backend when possible, the subprocess backend otherwise.

    Import failure is a real case, not paranoia: `grpcio` is the sidecar's one
    large binary wheel, and the dependency policy's whole concern is installs
    failing on lab machines. A machine where it didn't install keeps flashing
    through the proven `--format json` path — with a loud log line, because a
    silent degradation would defeat the migration without anyone noticing.
    """
    from .cli_tool import ArduinoCliTool

    if os.environ.get(NO_DAEMON_ENV):
        log.info("%s set; using the subprocess arduino-cli backend", NO_DAEMON_ENV)
        return ArduinoCliTool(app_data_dir=app_data_dir)
    try:
        from .grpc_tool import GrpcBoardTool
    except ImportError as exc:
        log.warning(
            "grpcio unavailable (%s); falling back to the subprocess "
            "arduino-cli backend — flashing still works, without live "
            "compiler streaming",
            exc,
        )
        return ArduinoCliTool(app_data_dir=app_data_dir)
    return GrpcBoardTool(app_data_dir=app_data_dir)
