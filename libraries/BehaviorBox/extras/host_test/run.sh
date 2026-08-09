#!/bin/sh
# Host-compile BehaviorBox.h against a minimal Arduino.h shim and run the logic
# tests (parseStartCommand, CorrectionPolicy, AbstentionPenalty, AntiBiasSelector,
# generateTrials). This exercises the SHARED LIBRARY logic off-target -- it does
# NOT replace flashing the sketches to the rig (only arduino-cli does the full
# AVR compile).
#
# IT IS ALSO THE STRICTEST TYPE CHECK THESE SKETCHES GET, and that is not a
# nicety. The Arduino AVR core compiles with `-fpermissive -w`, so a genuine
# type error -- passing a `const TrialType*` where an `int` is expected, say --
# is only a *warning*, which the build then suppresses: `arduino-cli compile`
# prints a size report and exits 0 on code that is wrong. Nothing here uses
# -fpermissive, so the same mistake is an error.
#
# So when a shared signature changes, run this AND
#   arduino-cli compile --warnings all ...
# over every sketch. A plain compile will not tell you.
#
# Lives under extras/ so the Arduino build never compiles it.
#
# Usage:  sh run.sh
#
# On a Windows machine with no clang/gcc, MSVC Build Tools compile it unchanged:
#   cl /EHsc /std:c++14 /D_CRT_SECURE_NO_WARNINGS /I. /I..\.. test_behaviorbox.cpp
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="$HERE/../.."          # the BehaviorBox library root (holds BehaviorBox.h)
CXX="${CXX:-clang++}"
"$CXX" -std=c++11 -Wall -I"$HERE" -I"$LIB" "$HERE/test_behaviorbox.cpp" -o "$HERE/test"
"$HERE/test"
