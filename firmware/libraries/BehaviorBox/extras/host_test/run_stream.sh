#!/bin/sh
# Host-compile BehaviorBox.h against the instrumented shim in box_shim/ and run
# test_trial_stream.cpp: every outcome a trial can have, driven through
# emitTrialHeader() / runTrial() / emitTrialFooter() by scripting the IR beams
# against millis(), asserting the exact strobe sequence each one emits (stream
# grammar 2, docs/TASKS.md#stream-grammar).
#
# The sibling run.sh tests the policy classes against the inert shim; this one
# needs a clock that moves and beams that answer, which is what box_shim gives.
#
# Usage:  sh run_stream.sh
#
# On a Windows machine with no clang/gcc, MSVC Build Tools compile it unchanged:
#   cl /EHsc /std:c++14 /D_CRT_SECURE_NO_WARNINGS /Ibox_shim /I. /I..\.. /TP \
#      test_trial_stream.cpp
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="$HERE/../.."          # the BehaviorBox library root (holds BehaviorBox.h)
CXX="${CXX:-clang++}"
# box_shim first: its Arduino.h must win over the inert one beside this script.
"$CXX" -std=c++11 -Wall -Wno-unused-function \
  -I"$HERE/box_shim" -I"$HERE" -I"$LIB" \
  -x c++ "$HERE/test_trial_stream.cpp" -o "$HERE/test_stream"
"$HERE/test_stream"
