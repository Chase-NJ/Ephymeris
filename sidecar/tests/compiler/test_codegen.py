"""Generated files must be current, and the layout must be expressible.

The `--check` mode is the CI guard. Without it a layout change would silently
diverge from the header the firmware compiles against, which is the exact hazard
the generator exists to close.
"""

from __future__ import annotations

import pytest

from ephymeris_sidecar.taskgraph.codegen import generate_all, outputs
from ephymeris_sidecar.taskgraph.codegen.layout import RECORDS


def test_generated_files_are_current():
    assert generate_all(check=True) == 0, (
        "generated header is stale -- run `taskgraph codegen` and commit the result"
    )


def test_generated_header_exists_and_is_marked():
    for path, text in outputs().items():
        assert path.exists(), f"{path} was never generated"
        assert "DO NOT EDIT" in text


@pytest.mark.parametrize("record", RECORDS, ids=lambda r: r.name)
def test_every_uint16_is_naturally_aligned(record):
    """THE rule that prevents the AVR/host divergence.

    A uint16 at an odd offset is packed by AVR (no alignment requirement) and
    padded by the host, so the record ends up a different size on each -- while
    compiling cleanly on both. TgTimingSet was exactly this: 3 bytes vs 4.

    record.offsets() raises if a uint16 lands odd, so this test is the guard that
    a future field addition cannot reintroduce it.
    """
    offsets = dict(record.offsets())
    for f in record.fields:
        if f.width == 2:
            assert offsets[f.name] % 2 == 0, (
                f"{record.name}.{f.name} is uint16 at odd offset {offsets[f.name]} -- "
                "AVR would pack it and the host would pad it"
            )


@pytest.mark.parametrize("record", RECORDS, ids=lambda r: r.name)
def test_declared_size_matches_the_fields(record):
    assert sum(f.width for f in record.fields) == record.size


def test_timing_set_carries_its_pad():
    """A regression guard on the specific record that proved the hazard."""
    rec = next(r for r in RECORDS if r.name == "TgTimingSet")
    assert any(f.name == "_pad" for f in rec.fields)
    assert rec.size == 4
