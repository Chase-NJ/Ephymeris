#!/bin/sh
# Host-compile TaskTable.h and check the record layout off-target.
#
# Deliberately mirrors the style of the reference repo's
# libraries/BehaviorBox/extras/host_test/run.sh -- same clang++ invocation, same
# extras/ placement so the Arduino build never compiles it.
#
# Today this only checks the table layout, because the interpreter is a Phase 3
# build. When that lands, the mock-clock and scripted-sensor tests join it here
# and this script grows a second binary, exactly as the BehaviorBox harness grew
# run_box.sh alongside run.sh.
#
# Usage:  sh run.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="$HERE/../.."          # the TaskInterpreter library root (holds TaskTable.h)
CXX="${CXX:-clang++}"
"$CXX" -std=c++11 -Wall -Wextra -I"$HERE" -I"$LIB" "$HERE/test_tasktable.cpp" -o "$HERE/test_tasktable"
"$HERE/test_tasktable"
