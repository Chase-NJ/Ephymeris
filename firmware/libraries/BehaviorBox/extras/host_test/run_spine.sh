#!/bin/sh
# Host-compile BoxSpine.h, the phase interpreter's hardware layer, against the
# instrumented shim in box_shim/ and a hand-written table (spine_fixture.h), and
# run its scenarios: the SET/PARAMS/CLAMPED handshake and the FREE_RAM
# announcement; the strobe stream's content, order and tick times, with
# skipped millis() values stepped, and an edge read on any of several loop()
# passes in one millisecond; and the session end rule, at the block's
# trial count, after STOP and after a last-trial state.
#
# The sidecar's test_spine_run.py compiles a GENERATED spine task the same way
# and plays it through the real session path; this is the firmware's own check,
# with no sidecar needed.
#
# Usage:  sh run_spine.sh
#
# On a Windows machine with no clang/gcc, MSVC Build Tools compile it unchanged:
#   cl /EHsc /std:c++14 /D_CRT_SECURE_NO_WARNINGS /Ibox_shim /I. /I..\.. /TP test_spine.cpp
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="$HERE/../.."          # the BehaviorBox library root
CXX="${CXX:-clang++}"
# box_shim first: its Arduino.h must win over the inert one beside this script.
"$CXX" -std=c++11 -Wall -Werror -Wno-unused-function \
  -I"$HERE/box_shim" -I"$HERE" -I"$LIB" \
  -x c++ "$HERE/test_spine.cpp" -o "$HERE/test_spine"
for scenario in handshake stream stop last blocks pairs passes; do
  "$HERE/test_spine" "$scenario"
done
# The same runner over spine_drive_fixture.h: PWM, tone and a pulse train.
"$CXX" -std=c++11 -Wall -Werror -Wno-unused-function -DSPINE_FIXTURE_DRIVES \
  -I"$HERE/box_shim" -I"$HERE" -I"$LIB" \
  -x c++ "$HERE/test_spine.cpp" -o "$HERE/test_spine_drives"
for scenario in drives train_held train_refused train_timing train_buffer; do
  "$HERE/test_spine_drives" "$scenario"
done
echo "test_spine: all passed"
