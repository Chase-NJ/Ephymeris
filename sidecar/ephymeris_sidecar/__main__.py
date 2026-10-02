"""Sidecar entrypoint.

Run directly during development:

    sidecar/.venv/bin/python -m ephymeris_sidecar

In the packaged app the Tauri shell spawns this and reads the handshake line
from stdout.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import secrets
import signal
import sys
from pathlib import Path

from .server import SidecarServer


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ephymeris-sidecar")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (loopback only)")
    parser.add_argument("--port", type=int, default=0, help="0 selects an ephemeral port")
    parser.add_argument("--token", default=None, help="auth token; generated when omitted")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--data-dir",
        default=None,
        help=(
            "app data directory holding ephymeris.db (DATA.md#sqlite-database). The Tauri "
            "shell passes its own app_data_dir; a platform default is used when "
            "running standalone."
        ),
    )
    parser.add_argument(
        "--no-parent-watch",
        action="store_true",
        help="do not exit when stdin closes (useful when running by hand)",
    )
    return parser


def _default_data_dir() -> Path:
    """Where the Tauri shell would put app data, for standalone dev runs."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "edu.hartlab.ephymeris"
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "edu.hartlab.ephymeris"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "edu.hartlab.ephymeris"


async def _run(args: argparse.Namespace) -> None:
    from .app import Application

    server = SidecarServer(
        host=args.host,
        port=args.port,
        token=args.token or secrets.token_urlsafe(32),
    )
    data_dir = Path(args.data_dir).expanduser() if args.data_dir else _default_data_dir()
    app = Application(server, data_dir=data_dir)
    app.register()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, server.request_shutdown)
        except NotImplementedError:  # pragma: no cover - Windows
            signal.signal(sig, lambda *_: server.request_shutdown())

    if not args.no_parent_watch:
        server.watch_parent_via_stdin()

    app.start()
    try:
        await server.run()
    finally:
        await app.stop()


def main() -> int:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        stream=sys.stderr,  # stdout is reserved for the handshake line
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
