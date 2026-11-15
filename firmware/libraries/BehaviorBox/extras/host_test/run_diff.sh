#!/bin/sh
# The differential test: BoxInterp.h, built for the host as interp_driver, and
# the Python replay (sidecar/ephymeris_sidecar/analytics/stream/replay.py) run
# the same tables and input logs, a third of the tables lowered by the generator
# itself (sidecar/ephymeris_sidecar/taskdef/lowering.py), and the test fails on
# the first tick where their actions differ, or the first pulse-train edge where
# they do. It then proves it can fail, by changing the Python tie rule and a
# train's rise and expecting a difference. See differential.py.
#
# Needs python3 (3.12 or later) and nothing installed: replay.py is loaded by path.
#
# Usage:  sh run_diff.sh [--cases N] [--seed S]
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="$HERE/../.."          # the BehaviorBox library root (holds BoxInterp.h)
CXX="${CXX:-clang++}"
PYTHON="${PYTHON:-python3}"
"$CXX" -std=c++11 -Wall -Wextra -Wconversion -Werror -I"$LIB" "$HERE/interp_driver.cpp" -o "$HERE/interp_driver"
"$PYTHON" "$HERE/differential.py" --driver "$HERE/interp_driver" "$@"
