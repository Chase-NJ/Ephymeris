"""Generate the arduino-cli gRPC stubs from the vendored protos.

Same discipline as the wire-protocol mirrors (`protocol/schema.py`): the
generated files are **committed**, so codegen is a development step, never an
install step — the lab machines only ever see finished stubs, and `grpcio-tools`
stays a dev dependency.

    sidecar$ .venv/Scripts/python -m scripts.gen_grpc      (or python scripts/gen_grpc.py)

The protos under `proto/` are copied verbatim from arduino-cli at the tag named
below (plus `google/rpc/status.proto` from googleapis, which they import).
When bumping the bundled/lab arduino-cli, re-vendor at the matching tag and
re-run this — the daemon and its client must agree on the schema.
"""

from __future__ import annotations

import sys
from pathlib import Path

#: The arduino-cli release the vendored protos were taken from. Kept next to
#: the codegen so "which version are these?" has one answer.
ARDUINO_CLI_TAG = "v1.5.1"

SIDECAR = Path(__file__).resolve().parent.parent
PROTO_DIR = SIDECAR / "proto"
OUT_DIR = SIDECAR / "ephymeris_sidecar" / "boards" / "rpc"


def main() -> int:
    try:
        from grpc_tools import protoc
    except ImportError:
        print("grpcio-tools is not installed — pip install -e '.[dev]'", file=sys.stderr)
        return 1

    protos = sorted(PROTO_DIR.rglob("*.proto"))
    if not protos:
        print(f"no .proto files under {PROTO_DIR}", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # The well-known types (`google/protobuf/any.proto`, imported by
    # debug.proto and status.proto) ship inside grpcio-tools; without this
    # include path they would have to be vendored too.
    well_known = Path(protoc.__file__).resolve().parent / "_proto"

    args = [
        "protoc",
        f"-I{PROTO_DIR}",
        f"-I{well_known}",
        f"--python_out={OUT_DIR}",
        # Service stubs only exist in commands.proto, but emitting the (tiny)
        # _pb2_grpc for every file keeps the invocation uniform.
        f"--grpc_python_out={OUT_DIR}",
        *[str(p) for p in protos],
    ]
    rc = protoc.main(args)
    if rc != 0:
        return rc

    # The generated tree uses absolute `cc.arduino...` / `google.rpc` imports;
    # `boards/rpc/__init__.py` puts itself on sys.path so they resolve. Marker
    # files record provenance for anyone wondering where these came from.
    (OUT_DIR / "VENDORED").write_text(
        f"Generated from arduino-cli {ARDUINO_CLI_TAG} protos by scripts/gen_grpc.py.\n"
        "Do not edit by hand — re-vendor and re-run the script instead.\n",
        encoding="utf-8",
    )
    print(f"wrote stubs for {len(protos)} protos to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
