"""Generated arduino-cli gRPC stubs (see `scripts/gen_grpc.py`).

The generated modules import each other absolutely (`cc.arduino.cli...`,
`google.rpc`), exactly as protoc emits them — rewriting those imports would
mean patching generated code on every regeneration. Instead this package puts
its own directory on `sys.path`, so the vendored `cc/` and `google/` trees
resolve as top-level (namespace) packages.

`google/` here contains only `google.rpc` — `google.protobuf` keeps coming
from the installed `protobuf` wheel, which namespace-package resolution merges
correctly with this directory.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    # Appended, not prepended: the installed `protobuf` package must keep
    # winning for `google.protobuf`; only what isn't installed (`cc`,
    # `google.rpc`) should fall through to the vendored tree.
    sys.path.append(_HERE)
