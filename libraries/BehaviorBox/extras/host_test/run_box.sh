#!/bin/sh
# Host-compile Utility/BOX_Utility.ino against the instrumented shim in
# box_shim/ and run its logic tests (channel tokens, TOGGLE/PULSE/ON/OFF,
# SET PULSE bounds, ALLOFF, the self-test's phases and pass tally).
#
# The sibling run.sh tests the shared library's policy classes against the inert
# shim; this tests a whole sketch against a shim that records pin writes and
# serial traffic. Neither replaces flashing to the rig -- only arduino-cli does
# the full AVR compile, and only a real box proves a solenoid fires.
#
# Usage:  sh run_box.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="$HERE/../.."          # the BehaviorBox library root (holds BehaviorBox.h)
CXX="${CXX:-clang++}"
# box_shim first: its Arduino.h must win over the inert one beside this script.
"$CXX" -std=c++11 -Wall -Wno-unused-function \
  -I"$HERE/box_shim" -I"$LIB" \
  -x c++ "$HERE/test_box_utility.cpp" -o "$HERE/test_box"
"$HERE/test_box"
