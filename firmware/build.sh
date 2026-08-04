#!/bin/sh
# Compile a sketch in this folder against BOTH library roots.
#
# The two-root invocation is the whole point of this script. BehaviorBox.h stays
# in the firmware repo as its single source -- it is not vendored here, because a
# second copy would drift, and drifting mirrors are the failure mode this project
# already documents twice (START_LINE_MAX and baudRate). So the build points at
# the reference repo for the shared hardware layer and at this repo for the
# interpreter, and neither copy exists twice.
#
# Override the firmware repo location if it is not the sibling default:
#   BEHAVIORBOX_REPO=/path/to/Arduino sh build.sh TaskRunner_Dev
#
# Usage:  sh build.sh [sketch-dir] [extra arduino-cli args...]
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
SKETCH="${1:-TaskRunner_Dev}"
[ $# -gt 0 ] && shift

BEHAVIORBOX_REPO="${BEHAVIORBOX_REPO:-$(cd "$REPO/.." && pwd)/Arduino}"
FQBN="${FQBN:-arduino:avr:mega}"
BUILD_DIR="${BUILD_DIR:-/tmp/taskgraph-build/$SKETCH}"

if [ ! -f "$BEHAVIORBOX_REPO/libraries/BehaviorBox/BehaviorBox.h" ]; then
  echo "error: BehaviorBox.h not found under $BEHAVIORBOX_REPO" >&2
  echo "       set BEHAVIORBOX_REPO to the firmware repo root" >&2
  exit 1
fi

echo "sketch  $SKETCH"
echo "fqbn    $FQBN"
echo "libs    $BEHAVIORBOX_REPO/libraries  (read-only reference)"
echo "        $HERE/libraries              (this repo)"
echo

arduino-cli compile \
  --fqbn "$FQBN" \
  --libraries "$BEHAVIORBOX_REPO/libraries" \
  --libraries "$HERE/libraries" \
  --build-path "$BUILD_DIR" \
  "$HERE/$SKETCH" "$@"
