#!/bin/sh
# Phase 3, the equivalence gate. Runs entirely off-target: no board, no animal.
#
# BehaviorBox.h comes from the READ-ONLY reference repo and is never modified.
# Override its location if the firmware repo is not the sibling default:
#   BEHAVIORBOX_REPO=/path/to/Arduino sh run_equivalence.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="$HERE/../.."
REPO="$(cd "$LIB/../../.." && pwd)"
BEHAVIORBOX_REPO="${BEHAVIORBOX_REPO:-$(cd "$REPO/.." && pwd)/Arduino}"
BB="$BEHAVIORBOX_REPO/libraries/BehaviorBox"
CXX="${CXX:-clang++}"

if [ ! -f "$BB/BehaviorBox.h" ]; then
  echo "error: BehaviorBox.h not found under $BB" >&2
  echo "       set BEHAVIORBOX_REPO to the firmware repo root" >&2
  exit 1
fi

# The shim MUST come first on the include path: it shadows the reference repo's
# own Arduino.h, whose millis() never advances.
"$CXX" -std=c++17 -Wall -Wextra -I"$HERE" -I"$LIB" -I"$BB" \
  "$HERE/smoke_runtrial.cpp" -o "$HERE/smoke_runtrial"
"$HERE/smoke_runtrial"
