"""Pinning the legacy adapter to the scorer it replaced (`ANALYTICS.md#how-a-legacy-run-becomes-a-trial-table`).

Everything a legacy run reports, as one canonical value per run: its summary
payload, its rolling and cumulative series, its strategy trail and its tape.
`outputs` builds it through calls the scorer before the adapter (2b851fd) and
the adapter both answer, so the same file measures either side:

    # on a checkout of 2b851fd, then on this branch:
    python -m tests.legacy_corpus capture <archive> > before.json
    python -m tests.legacy_corpus check <archive> before.json

`capture` writes the per-sketch pin `test_legacy_corpus.py` reads (run count,
a digest over every run's outputs, summed totals); `check` re-scores the
archive and names every sketch whose outputs moved. `pin` writes the
synthetic fixture `test_legacy_pin.py` reads. Run it from `sidecar/`, as a module, so it
scores with this checkout's code and not whatever the venv installed.

The profile each run is scored with is the one `scoring._settle` reaches with
no database: the file's own snapshot, else the bundled sketch for its name
(folder or `legacyNames`), else inference, all under the shipped seed
vocabulary, so the answer depends on the file and the code alone.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any

from ephymeris_sidecar.analytics import scoring, stream
from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.rig.registry import Vocabulary
from ephymeris_sidecar.tasks import profile as task_profile

FIRMWARE = Path(__file__).resolve().parents[2] / "firmware"


def seed_vocabulary() -> Vocabulary:
    return Vocabulary(registry.default_vocabulary_document())


def outputs(document: dict[str, Any], profile: task_profile.TaskProfile | None,
            vocabulary: Vocabulary, source: str = "snapshot") -> dict[str, Any]:
    """Everything a legacy run reports, scored as `analytics.summary` and
    `analytics.series` score it. `profile` is what resolution found (None for
    nothing) and `source` which rung; `_settle` takes the ladder's last rungs."""
    if profile is not None:
        resolved = scoring._Resolved(profile, source, task_profile.profile_hash(profile))
    else:
        resolved = scoring._Resolved(None, "unavailable", None, "nothing resolves")
    settled, source, _ = scoring._settle(resolved, document, scoring._Pass(vocabulary, remember=None))
    return {
        "source": source,
        "summary": stream.summarize(document, settled).to_json(),
        "rolling": [m.to_json() for m in stream.series(document, settled)],
        "cumulative": [m.to_json() for m in stream.series(document, settled, mode="cumulative")],
        "trail": [p.to_json() for p in stream.strategy_trail(document, settled)],
        "tape": [t.to_json() for t in stream.trials_of(document, settled)],
    }


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# --- the recorded corpus ---------------------------------------------------------


def bundled_profiles(vocabulary: Vocabulary) -> dict[str, task_profile.TaskProfile]:
    """Every bundled sketch's profile by folder name, then by each `legacyNames` entry."""
    by_name: dict[str, task_profile.TaskProfile] = {}
    declared = []
    for path in sorted(FIRMWARE.rglob("task.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        profile = task_profile.parse_profile(raw, vocabulary)
        by_name.setdefault(path.parent.name, profile)
        declared.append((raw.get("legacyNames") or [], profile))
    for names, profile in declared:
        for name in names:
            by_name.setdefault(name, profile)
    return by_name


def runs(archive: Path) -> list[tuple[str, dict[str, Any]]]:
    """Every run file under `archive`: a JSON object with `ts_data`, by relative path."""
    out = []
    for path in sorted(archive.rglob("*.json")):
        if not path.is_file():
            continue
        try:
            document = json.loads(path.read_bytes())
        except ValueError:
            continue
        if isinstance(document, dict) and "ts_data" in document:
            out.append((path.relative_to(archive).as_posix(), document))
    return out


def corpus(archive: Path) -> dict[str, dict[str, Any]]:
    """Per sketch name: run count, a digest over every run's outputs, and totals."""
    vocabulary = seed_vocabulary()
    library = bundled_profiles(vocabulary)
    per_sketch: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for path, document in runs(archive):
        sketch = document.get("sketch")
        name = sketch if isinstance(sketch, str) else ""
        profile = library.get(name)
        per_sketch.setdefault(name, []).append((digest(document.get("ts_data")),
                                               outputs(document, profile, vocabulary, "sketch-current")))
    pin: dict[str, dict[str, Any]] = {}
    for name, entries in sorted(per_sketch.items()):
        entries.sort(key=lambda e: e[0])
        pin[name] = {
            "runs": len(entries),
            "digest": digest([out for _, out in entries]),
            "totals": totals([out["summary"] for _, out in entries]),
        }
    return pin


def totals(summaries: list[dict[str, Any]]) -> dict[str, int]:
    """Counted, hits, outcome tallies and engagement, summed over runs."""
    out: dict[str, int] = {}

    def add(key: str, value: Any) -> None:
        if isinstance(value, int) and not isinstance(value, bool):
            out[key] = out.get(key, 0) + value

    for summary in summaries:
        add("runs-ok", 1 if summary["status"] == "ok" else 0)
        for metric in summary["metrics"]:
            for key in ("counted", "hits", "triggered", "excluded"):
                add(f"metrics.{key}", metric[key])
        for key in ("trials", "administered", "rewarded", "holdFailed", "wrongWell", "noResponse", "aborted"):
            add(f"outcomes.{key}", (summary["outcomes"] or {}).get(key))
        for key in ("presented", "poked", "odorDelivered"):
            add(f"engagement.{key}", (summary["engagement"] or {}).get(key))
    return out


# --- the synthetic pin -------------------------------------------------------------


def synthetic_cases(vocabulary: Vocabulary) -> list[dict[str, Any]]:
    """Documents and profiles covering every branch the adapter must keep:
    each bundled sketch, each corpus profile shape, no-go, a profile missing
    the trial light or the reward vocabulary, two conditions on one onset,
    broken clocks, and seeded random streams. Profiles are stored as JSON, so
    the fixture alone reproduces them."""
    code = vocabulary.code_of
    strobes = {str(c): n for c, n in vocabulary.code_map().items()}

    def metric(mid: str, onset: str, success: str, *alternates: str, window: int = 5) -> dict[str, Any]:
        return {"id": mid, "label": mid, "triggerCode": code(onset), "successCode": code(success),
                "alternateCodes": [code(a) for a in alternates], "windowSize": window}

    def profile(metrics: list[dict[str, Any]], *, names: dict[str, str] | None = None,
                kind: str = "behavior") -> dict[str, Any]:
        return {"taskName": "Pin", "kind": kind, "strobes": names if names is not None else strobes,
                "liveMetrics": metrics}

    def odors(n: int, window: int = 20) -> dict[str, Any]:
        return profile([metric(f"o{k}", f"ODOR_{k}_ON", "WATER_POKE_R" if k % 2 else "WATER_POKE_L",
                               "WATER_POKE_L" if k % 2 else "WATER_POKE_R", window=window)
                        for k in range(1, n + 1)])

    no_go = profile([
        metric("go_r", "ODOR_1_ON", "WATER_POKE_R", "WATER_POKE_L"),
        metric("go_l", "ODOR_3_ON", "WATER_POKE_L", "WATER_POKE_R"),
        metric("nogo", "ODOR_5_ON", "WATER_POKE_NONE", "WATER_POKE_L", "WATER_POKE_R"),
    ])
    pre_fix = profile([*no_go["liveMetrics"][:2],
                       metric("nogo", "ODOR_5_ON", "WATER_POKE_NONE", "WATER_POKE_R")])
    shared = profile([
        metric("r_on_1", "ODOR_1_ON", "WATER_POKE_R", "WATER_POKE_L", window=3),
        metric("l_on_1", "ODOR_1_ON", "WATER_POKE_L", "WATER_POKE_R", window=4),
        metric("l_on_3", "ODOR_3_ON", "WATER_POKE_L", "WATER_POKE_R"),
    ])
    keep = {"LIGHTS_ON", "LIGHTS_OFF", "ODOR_POKE"}
    no_reward = profile(odors(2)["liveMetrics"], names={
        c: n for c, n in strobes.items() if not n.startswith(("FLUID", "ODOR_UNPOKE"))})
    no_light = profile(odors(2)["liveMetrics"], names={
        c: n for c, n in strobes.items() if n not in keep})
    library = bundled_profiles(vocabulary)

    def trial(onset: str, *answer: str) -> list[str]:
        return ["LIGHTS_ON", "ODOR_POKE", onset, "ODOR_UNPOKE", *answer]

    session = (
        trial("ODOR_1_ON", "WATER_POKE_R", "FLUID_R", "STOP_FLUID_G_R") * 4
        + trial("ODOR_1_ON", "WATER_POKE_L", "WATER_POKE_ERROR_L")
        + trial("ODOR_3_ON", "WATER_POKE_L", "WATER_UNPOKE_EARLY_L")
        + trial("ODOR_3_ON", "WATER_POKE_L", "FLUID_L", "STOP_FLUID_G_L") * 3
        + trial("ODOR_5_ON", "WATER_POKE_NONE") + trial("ODOR_5_ON", "WATER_POKE_L")
        + trial("ODOR_5_ON", "WATER_POKE_R") + trial("ODOR_5_ON")
        + ["LIGHTS_ON", "LAZY_RAT", "LIGHTS_OFF"] + ["LIGHTS_ON", "ODOR_POKE", "LIGHTS_OFF"]
        + ["LIGHTS_ON", "ODOR_POKE", "ODOR_3_ON", "ODOR_UNPOKE_EARLY"]
        + trial("ODOR_2_ON", "WATER_POKE_L", "FLUID_L") + trial("ODOR_4_ON", "WATER_POKE_L")
        + trial("ODOR_7_ON", "WATER_POKE_R", "FLUID_R") + trial("ODOR_8_ON", "WATER_POKE_R")
        + trial("ODOR_1_ON")
    )

    def document(names: list[str], clock: str = "steady") -> dict[str, Any]:
        codes = [code("START_SESSION"), *(code(n) for n in names), code("END_SESSION")]
        if clock == "steady":
            stamps: list[Any] = [i * 250 for i in range(len(codes))]
        elif clock == "none":
            stamps = [None] * len(codes)
        else:  # disordered, with gaps
            stamps = [None if i % 7 == 3 else (i * 250 if i % 5 else i * 250 - 900) for i in range(len(codes))]
        return {"rat": "pin", "sketch": "Pin", "stop_reason": stream.CLEAN_STOP_REASON,
                "trial_seed": 3, "n_events": len(codes), "ts_data": [[c, t] for c, t in zip(codes, stamps)]}

    cases: list[dict[str, Any]] = []

    def case(name: str, raw: dict[str, Any] | None, doc: dict[str, Any]) -> None:
        cases.append({"name": name, "profile": raw, "document": doc})

    for sketch in ("GRGL", "GRGL_Sim", "BOX_Utility"):
        case(f"bundled-{sketch}", library[sketch].to_json(), document(session))
    for n in (2, 4, 6, 8):
        case(f"odors-{n}", odors(n), document(session))
    case("odors-2-window-1", odors(2, window=1), document(session))
    case("inferred", None, document(session))
    case("no-go", no_go, document(session))
    case("no-go-pre-fix", pre_fix, document(session))
    case("shared-onset", shared, document(session))
    case("no-reward-vocabulary", no_reward, document(session))
    case("no-trial-light", no_light, document(session))
    case("clock-none", no_go, document(session, "none"))
    case("clock-disordered", no_go, document(session, "disordered"))
    case("empty", no_go, document([]))
    case("before-first-light", no_go, document(["ODOR_1_ON", "WATER_POKE_R", "FLUID_R", *session[:9]]))
    case("two-onsets-one-light", no_go, document(
        ["LIGHTS_ON", "ODOR_POKE", "ODOR_1_ON", "ODOR_3_ON", "WATER_POKE_L", "FLUID_L", *session[:5]]))

    alphabet = ["LIGHTS_ON", "LIGHTS_OFF", "ODOR_POKE", "ODOR_UNPOKE", "ODOR_UNPOKE_EARLY", "LAZY_RAT",
                "ODOR_1_ON", "ODOR_3_ON", "ODOR_5_ON", "WATER_POKE_L", "WATER_POKE_R", "WATER_POKE_NONE",
                "FLUID_L", "FLUID_R", "STOP_FLUID_G_L", "STOP_FLUID_G_R", "WATER_UNPOKE_EARLY_L",
                "WATER_UNPOKE_EARLY_R", "WATER_POKE_ERROR_L", "WATER_POKE_ERROR_R", "WATER_UNPOKE_R"]
    rng = random.Random(107)
    shapes = [no_go, shared, library["GRGL"].to_json(), no_light, None]
    for i in range(100):
        names = [alphabet[int(rng.random() * len(alphabet))] for _ in range(int(rng.random() * 80))]
        clock = ("steady", "steady", "disordered", "none")[i % 4]
        case(f"random-{i}", shapes[i % len(shapes)], document(names, clock))
    return cases


def pin_fixture() -> dict[str, Any]:
    vocabulary = seed_vocabulary()
    cases = synthetic_cases(vocabulary)
    for entry in cases:
        raw = entry["profile"]
        profile = task_profile.parse_profile(raw) if raw is not None else None
        entry["expected"] = outputs(entry["document"], profile, vocabulary)
    return {"capturedFrom": "origin/main 2b851fd, before the legacy adapter", "cases": cases}


def main(argv: list[str]) -> int:
    if argv[:1] == ["pin"]:
        print(json.dumps(pin_fixture(), sort_keys=True, separators=(",", ":")))
        return 0
    if argv[:1] == ["capture"] and len(argv) == 2:
        print(json.dumps(corpus(Path(argv[1])), sort_keys=True, indent=1))
        return 0
    if argv[:1] == ["check"] and len(argv) == 3:
        want = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        got = corpus(Path(argv[1]))
        moved = sorted(name for name in set(want) | set(got) if want.get(name) != got.get(name))
        for name in moved:
            print(f"{name!r}: was {want.get(name)}, now {got.get(name)}")
        print(f"{len(got) - len(moved)} of {len(got)} sketches unchanged")
        return 1 if moved else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
