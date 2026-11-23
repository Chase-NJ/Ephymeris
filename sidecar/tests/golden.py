"""What one archived run file reads and scores to, as one comparable value.

`golden/runs/` holds real per-animal files copied from the archive, one per
sketch and per way a run can end, plus `synthetic_*` logs for damage the
archive does not contain. `golden/expected/<file>.json` is what each read to
when it was captured. Capture only from a commit whose output you trust:

    python -m tests.golden capture
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ephymeris_sidecar.analytics import reader
from ephymeris_sidecar.sessions import recovery

from .legacy_corpus import bundled_profiles, digest, outputs, seed_vocabulary

GOLDEN = Path(__file__).parent / "golden"
RUNS = GOLDEN / "runs"
EXPECTED = GOLDEN / "expected"

DIGESTED = ("rolling", "cumulative", "trail", "tape")


def cases() -> list[Path]:
    return sorted(p for p in RUNS.iterdir() if p.suffix in (".tsv", ".json"))


def expected_path(run: Path) -> Path:
    return EXPECTED / f"{run.name}.json"


def scored(document: dict[str, Any]) -> dict[str, Any]:
    vocabulary = seed_vocabulary()
    sketch = document.get("sketch")
    profile = bundled_profiles(vocabulary).get(sketch if isinstance(sketch, str) else "")
    out = outputs(document, profile, vocabulary, "sketch-current")
    return {
        "source": out["source"],
        "summary": out["summary"],
        "trials": len(out["tape"]),
        **{key: digest(out[key]) for key in DIGESTED},
    }


def fingerprint(run: Path) -> dict[str, Any]:
    if run.suffix == ".tsv":
        parsed = recovery.parse_tsv(run)
        document = recovery.recovered_document(parsed)
        return {
            "dialect": parsed.dialect,
            "stop_reason": parsed.stop_reason,
            "header": sorted(parsed.metadata),
            "header_digest": digest(parsed.metadata),
            "strobes": len(parsed.events),
            "strobe_digest": digest(parsed.events),
            "document_digest": digest(document),
            **scored(document),
        }
    result = reader.read_run(run)
    if result.document is None:
        return {"status": result.status}
    return {"status": result.status, "document_digest": digest(result.document), **scored(result.document)}


def main(argv: list[str]) -> int:
    if argv != ["capture"]:
        print(__doc__)
        return 2
    EXPECTED.mkdir(exist_ok=True)
    for run in cases():
        text = json.dumps(fingerprint(run), sort_keys=True, indent=1) + "\n"
        expected_path(run).write_text(text, encoding="utf-8")
    print(f"captured {len(cases())} files")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
