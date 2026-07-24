#!/bin/sh
# Host-compile BehaviorBox.h against a minimal Arduino.h shim and run the logic
# tests (parseStartCommand, CorrectionPolicy, AbstentionPenalty, AntiBiasSelector,
# generateTrials). This exercises the SHARED LIBRARY logic off-target -- it does
# NOT replace flashing the sketches to the rig (only arduino-cli does the full
# AVR compile).
#
# Lives under extras/ so the Arduino build never compiles it.
#
# Usage:  sh run.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="$HERE/../.."          # the BehaviorBox library root (holds BehaviorBox.h)
CXX="${CXX:-clang++}"
"$CXX" -std=c++11 -Wall -I"$HERE" -I"$LIB" "$HERE/test_behaviorbox.cpp" -o "$HERE/test"
"$HERE/test"
