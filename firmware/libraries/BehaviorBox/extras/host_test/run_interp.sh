#!/bin/sh
# Host-compile BoxInterp.h, the phase interpreter's pure core, and run its tests
# (the session RNG against Park and Miller's published check value, the tick
# rules, the chance branch, drawn durations, the millis() wrap).
#
# BoxInterp.h includes no Arduino header, so unlike run.sh this needs no shim.
# The sibling run_diff.sh holds the core equal to the Python replay.
#
# Usage:  sh run_interp.sh
#
# On a Windows machine with no clang/gcc, MSVC Build Tools compile it unchanged:
#   cl /EHsc /std:c++14 /I..\.. test_interp.cpp
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="$HERE/../.."          # the BehaviorBox library root (holds BoxInterp.h)
CXX="${CXX:-clang++}"
"$CXX" -std=c++11 -Wall -Wextra -Wconversion -Werror -I"$LIB" "$HERE/test_interp.cpp" -o "$HERE/test_interp"
"$HERE/test_interp"
