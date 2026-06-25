#!/bin/sh
# Host-compile GRGLSession.h against a minimal Arduino.h shim and run the logic
# tests (parseStartCommand, CorrectionPolicy, AbstentionPenalty, AntiBiasSelector).
# This exercises the SHARED LIBRARY logic off-target -- it does NOT replace
# flashing the sketches to the rig (only arduino-cli does the full compile).
#
# Lives under extras/ so the Arduino build never compiles it.
#
# Usage:  sh run.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="$HERE/../.."          # the GRGLSession library root (holds GRGLSession.h)
CXX="${CXX:-clang++}"
"$CXX" -std=c++11 -Wall -I"$HERE" -I"$LIB" "$HERE/test_grglsession.cpp" -o "$HERE/test"
"$HERE/test"
