"""The seed spines a new task starts from (`TASKS.md#the-spine-editor`).

ADR 0003's five: 2AFC, go/no-go, DNMS, trace and a ratio schedule. Each is a
whole spine-task document, the one source the editor reads through
`tasks.spinePalette`.

A SEED CARRIES PHASES AND NO NAMES. Its slots are roles (`port`, `sample`),
its phases, its rows' maps and its block are written out, but every row's
`name` is empty and every `bind` is empty. A condition's name and the channel
that carries it differ on every bench, and a guessed one is wrong for everyone
but its author, so a new task opens with SPN108 and SPN101 on each row until
the operator names and binds it (`TASKS.md#what-a-definition-holds`). Row ids
are neutral (`row_1`, …): they name the row's parameters and never show.
"""

from __future__ import annotations

from typing import Any

from . import pavlovian

_PORT_WAIT = [
    {"phase": "wait", "on": "port", "outputs": ["cue"]},
    {"phase": "hold", "on": "port", "outputs": ["cue"], "ms": 200},
]


def _row(n: int, **fields: Any) -> dict[str, Any]:
    return {"id": f"row_{n}", "name": "", "bind": {}, "rewardMs": 100, "rewardPermille": 1000, **fields}


def _pays(line: str, hold: bool = False) -> dict[str, Any]:
    entry: dict[str, Any] = {"outcome": "correct", "line": line, "rewardPermille": 1000}
    if hold:
        entry["hold"] = True
    return entry


def _document(slots: list[tuple[str, str]], spine: list[dict], rows: list[dict], trials: int) -> dict[str, Any]:
    return {
        "id": "new_task",
        "name": "New task",
        "category": "Tasks",
        "slots": [{"id": slot, "type": kind} for slot, kind in slots],
        "spine": spine,
        "rows": rows,
        "blocks": [{"id": "b1", "rows": [r["id"] for r in rows], "trials": trials}],
        "params": {},
        "legacyNames": [],
        "notes": "",
    }


_IN, _OUT = "digital_in", "digital_out"

#: Trace conditioning's own slots and phases, with a level CS each row binds.
_TRACE = pavlovian.phases(trace=True, tone=False)

#: In the order the editor offers them.
SEEDS: list[dict[str, Any]] = [
    {
        "id": "two_afc",
        "label": "2AFC",
        "summary": "Poke and hold, a stimulus, then a choice of two ports; each row pays at one, held.",
        "definition": _document(
            [("port", _IN), ("left", _IN), ("right", _IN), ("cue", _OUT), ("sample", _OUT),
             ("reward_l", _OUT), ("reward_r", _OUT)],
            [*_PORT_WAIT,
             {"phase": "present", "outputs": ["cue", "sample"], "ms": 1000, "abortOnRelease": "port"},
             {"phase": "response", "responses": ["left", "right"], "ms": 5000, "holdMs": 200},
             {"phase": "outcome", "ms": 0},
             {"phase": "iti", "ms": 3000}],
            [_row(1, map={"left": _pays("reward_l", hold=True), "right": {"outcome": "wrong_response"},
                          "timeout": {"outcome": "omission"}}),
             _row(2, map={"left": {"outcome": "wrong_response"}, "right": _pays("reward_r", hold=True),
                          "timeout": {"outcome": "omission"}})],
            trials=200,
        ),
    },
    {
        "id": "go_no_go",
        "label": "Go/no-go",
        "summary": "Poke and hold, a stimulus, then one port: one row pays a response, the other asks to withhold.",
        "definition": _document(
            [("port", _IN), ("resp", _IN), ("cue", _OUT), ("sample", _OUT), ("reward", _OUT)],
            [*_PORT_WAIT,
             {"phase": "present", "outputs": ["cue", "sample"], "ms": 1000, "abortOnRelease": "port"},
             {"phase": "response", "responses": ["resp"], "ms": 3000},
             {"phase": "outcome", "ms": 0},
             {"phase": "iti", "ms": 3000}],
            [_row(1, map={"resp": _pays("reward"), "timeout": {"outcome": "omission"}}),
             _row(2, map={"resp": {"outcome": "false_alarm"}, "timeout": {"outcome": "withheld"}})],
            trials=200,
        ),
    },
    {
        "id": "dnms",
        "label": "DNMS",
        "summary": "A sample, a delay held at the port, a test, then a match or non-match port; "
                   "two rows match and two do not.",
        "definition": _document(
            [("port", _IN), ("match", _IN), ("non_match", _IN), ("cue", _OUT), ("sample", _OUT), ("test", _OUT),
             ("reward_l", _OUT), ("reward_r", _OUT)],
            [*_PORT_WAIT,
             {"phase": "present", "outputs": ["cue", "sample"], "ms": 1000, "abortOnRelease": "port"},
             {"phase": "delay", "outputs": ["cue"], "ms": 2000, "abortOnRelease": "port"},
             {"phase": "present", "outputs": ["cue", "test"], "ms": 1000, "abortOnRelease": "port"},
             {"phase": "response", "responses": ["match", "non_match"], "ms": 5000},
             {"phase": "outcome", "ms": 0},
             {"phase": "iti", "ms": 3000}],
            [_row(n, map={"match": _pays("reward_l") if same else {"outcome": "wrong_response"},
                          "non_match": {"outcome": "wrong_response"} if same else _pays("reward_r"),
                          "timeout": {"outcome": "omission"}})
             for n, same in ((1, True), (2, True), (3, False), (4, False))],
            trials=200,
        ),
    },
    {
        "id": "trace",
        "label": "Trace",
        "summary": "A baseline, a cue, a trace interval, then an outcome with no response asked, "
                   "licks counted in each: one row pays, the other does not.",
        "definition": _document(
            [(slot["id"], slot["type"]) for slot in _TRACE["slots"]],
            _TRACE["spine"],
            [_row(1), _row(2, rewardPermille=0)],
            trials=100,
        ),
    },
    {
        "id": "ratio",
        "label": "FR / PR",
        "summary": "Count presses to N, pay, again. N fixed (FR), drawn (VR) or from a progressive list (PR).",
        "definition": _document(
            [("lever", _IN), ("light", _OUT), ("reward", _OUT)],
            [{"phase": "counter", "on": "lever", "count": 5, "outputs": ["light"]},
             {"phase": "outcome", "line": "reward", "ms": 0},
             {"phase": "iti", "ms": 500}],
            [_row(1)],
            trials=100,
        ),
    },
]
