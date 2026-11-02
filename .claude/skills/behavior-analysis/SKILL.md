---
name: behavior-analysis
description: How Ephymeris turns a run's strobes into trials and accuracies (legacy decoder and spine replay), per-condition and per-side accuracy, the score cache, and the JSON-to-.mat mirror. Use when changing or debugging anything under sidecar/ephymeris_sidecar/analytics/, sessions/matwriter.py or sessions/derived.py, when a number in Analytics or Mission Control looks wrong, or when scoring a session file by hand.
---

# Behavior analysis

`ANALYTICS.md#start-here` is the source of truth; this skill tells you which section to read for a given question.

## The input

A run's `.json` holds raw strobes in `ts_data` as `[code, timestamp]` pairs, in the order the box sent them,
plus a header (`rat`, `sketch`, `stop_reason`, `trial_seed`, …) and the run's own profile snapshot
(`DATA.md#the-json-document`). The `.tsv` is the same stream written live (`DATA.md#the-tsv-log`). The app
never trusts a stored trial table: every trial and number is re-derived each time the run is read.

Codes mean nothing without the per-machine strobe vocabulary and the run's task profile
(`tasks/profile.py`'s `embedded_profile(document)`). Never hard-code a code number; look names up.

## Strobes → trials

| Run kind | Path | Read |
|---|---|---|
| Legacy (GRGL trial runner) | `stream/legacy/decode.py` `table_of` → trial table; `legacy/trials.py` `MetricAccumulator.offer(code)` classifies hit / miss / excluded one strobe at a time (Mission Control scores live with it too) | `ANALYTICS.md#how-a-legacy-run-becomes-a-trial-table`, `ANALYTICS.md#trials-hits-misses-and-exclusions` |
| Spine (state-table interpreter) | `stream/replay.py` re-runs the firmware's interpreter from table + params + seed + input edges; `stream/spine.py` `replayed(document)` compares and returns the divergence or the trial table; `stream/trial_table.py` builds the rows | `ANALYTICS.md#how-a-spine-run-is-scored`, `ANALYTICS.md#diverged-and-unreplayable-runs` |

Trial boundaries always come from `boundaries_for(profile)` (`ANALYTICS.md#boundary-codes`). No profile:
`legacy/infer.py` `infer_profile(codes)`; which profile wins is the ladder in `ANALYTICS.md#which-profile-decodes-a-run`.

## Trials → numbers

- Outcomes (rewarded, hold failure, wrong well, unanswered, aborted): `stream/outcomes.py`.
- Per-condition accuracy (a condition is an odor answered at a given well, i.e. a side): `conditions_of`,
  `table_metrics.legacy_metrics`; spine runs use `table_metrics.score` for P(correct | row).
  `ANALYTICS.md#per-condition-tally`, `ANALYTICS.md#rewarded-and-response-accuracy`, `ANALYTICS.md#pooled-accuracy`.
- Every number carries n and a 95% Wilson interval (`stream/stats.py`); nothing is suppressed. A run with
  nothing to score says why (`ANALYTICS.md#why-a-run-has-no-numbers`).
- Engagement ladder, learning curves, false starts: `engagement.py`, `curves.py`, `false_starts.py`.

To score one file by hand, use the snippet under `ANALYTICS.md#key-functions` (`summarize(document, profile)`).

## Caching

`scoring.py` caches each run's summary and serves it verbatim. Any scoring change must move the cache
version: see the canary rule in `DATA.md#caching` and `test_the_score_version_pins_every_input`.

## JSON ↔ MATLAB

- `.json` → `.mat`: `sessions/matwriter.py` `savemat(path, document)` via `to_matlab`, which forces the
  MATLAB classes the lab's code expects (`DATA.md#the-mat-mirror`). A spine run's derived trial table goes
  into both files through `sessions/derived.py` (`DATA.md#the-derived-trial-table`).
- There is no `.mat` → `.json` reader: the app reads `.json` only. Orphaned `.tsv` files are rebuilt into
  `.json`/`.mat` by the archive walk (`analytics/archive.py`, `DATA.md#re-derive`).
- Legacy folders `behavior_json/`, `recovery_tsv/`, `behavior_mat/` are read as written (`analytics/reader.py`).

## Tests

`sidecar/tests/test_analytics_*.py`, `test_legacy_*.py`, `test_replay_trial_table.py`, `test_spine_analytics.py`,
`test_matwriter.py`, `test_derived_trials.py`. `test_analytics_stream_is_pure.py` keeps `stream/` free of
files, database and clock. Never open `fixtures/legacy_pin.json` or `legacy_corpus.json`; to inspect a case,
load it in Python and print only the fields you need.
