"""Auto-Balance grouping — `cohorts.md` §7."""

from __future__ import annotations

from collections import Counter

import pytest

from ephymeris_sidecar.cohorts.grouping import (
    minimum_group_count,
    resolve_group_count,
    suggest_groups,
)
from ephymeris_sidecar.cohorts.models import Animal


def make_animals(spec: str) -> list[Animal]:
    """`"MMFFuu"` -> six animals with those sexes ('u' = unknown)."""
    sexes = {"M": "M", "F": "F", "u": "unknown"}
    return [
        Animal(id=f"a{i}", name=f"A{i}", group_id="g", sex=sexes[ch])
        for i, ch in enumerate(spec)
    ]


def sizes(proposal) -> list[int]:  # noqa: ANN001
    return [len(g.animals) for g in proposal.groups]


# --- §7.1 inputs ----------------------------------------------------------


def test_group_count_and_max_size_are_interchangeable() -> None:
    assert resolve_group_count(12, group_count=3, max_group_size=None) == 3
    assert resolve_group_count(12, group_count=None, max_group_size=4) == 3
    # A ragged split rounds up rather than overflowing the last group.
    assert resolve_group_count(10, group_count=None, max_group_size=4) == 3


def test_neither_input_falls_back_to_the_minimum_viable_split() -> None:
    assert resolve_group_count(10, None, None) == 2


# --- §7.2 hard constraint -------------------------------------------------


def test_no_group_may_exceed_six() -> None:
    proposal = suggest_groups(make_animals("M" * 10), group_count=1)
    assert proposal.groups == []
    assert proposal.rejected is not None
    # It answers with guidance rather than a bare failure.
    assert proposal.rejected["minimumGroups"] == 2


@pytest.mark.parametrize(
    ("count", "expected"), [(1, 1), (6, 1), (7, 2), (12, 2), (13, 3)]
)
def test_minimum_group_count_is_ceil_over_six(count: int, expected: int) -> None:
    assert minimum_group_count(count) == expected


def test_a_request_at_exactly_the_limit_is_allowed() -> None:
    proposal = suggest_groups(make_animals("M" * 12), group_count=2)
    assert proposal.rejected is None
    assert sizes(proposal) == [6, 6]


# --- §7.3 round-robin -----------------------------------------------------


def test_group_sizes_stay_within_one_of_each_other() -> None:
    proposal = suggest_groups(make_animals("M" * 7), group_count=3)
    assert max(sizes(proposal)) - min(sizes(proposal)) <= 1


def test_sex_balance_spreads_each_bucket_across_groups() -> None:
    # 4M + 4F into 2 groups should give each group 2M + 2F.
    proposal = suggest_groups(make_animals("MMMMFFFF"), group_count=2, balance_by_sex=True)
    lookup = {a.id: a.sex for a in make_animals("MMMMFFFF")}
    for group in proposal.groups:
        counts = Counter(lookup[a.animal_id] for a in group.animals)
        assert counts["M"] == 2
        assert counts["F"] == 2


def test_unknown_sex_animals_do_not_skew_the_balance() -> None:
    """§7.3 step 3 — they fill in size-wise after the known buckets."""
    animals = make_animals("MMFFuu")
    proposal = suggest_groups(animals, group_count=2, balance_by_sex=True)
    lookup = {a.id: a.sex for a in animals}
    for group in proposal.groups:
        counts = Counter(lookup[a.animal_id] for a in group.animals)
        assert counts["M"] == 1
        assert counts["F"] == 1
        assert counts["unknown"] == 1


def test_balancing_off_still_produces_even_sizes() -> None:
    proposal = suggest_groups(make_animals("MMMMFF"), group_count=3, balance_by_sex=False)
    assert sizes(proposal) == [2, 2, 2]


def test_is_deterministic() -> None:
    animals = make_animals("MFMFMF")
    first = suggest_groups(animals, group_count=2, balance_by_sex=True).to_json()
    second = suggest_groups(animals, group_count=2, balance_by_sex=True).to_json()
    assert first == second


# --- §7.3 step 4: box numbering ------------------------------------------


def test_boxes_number_sequentially_within_each_group() -> None:
    proposal = suggest_groups(make_animals("M" * 9), group_count=2)
    for group in proposal.groups:
        boxes = [a.box_number for a in group.animals]
        assert boxes == list(range(1, len(boxes) + 1))


def test_box_numbers_repeat_across_groups() -> None:
    """§2 — groups run consecutively, so the same slot is reused."""
    proposal = suggest_groups(make_animals("M" * 4), group_count=2)
    assert [a.box_number for a in proposal.groups[0].animals] == [1, 2]
    assert [a.box_number for a in proposal.groups[1].animals] == [1, 2]


def test_boxes_never_exceed_the_six_slot_range() -> None:
    proposal = suggest_groups(make_animals("M" * 18), group_count=3)
    for group in proposal.groups:
        for animal in group.animals:
            assert 1 <= animal.box_number <= 6


# --- edge cases -----------------------------------------------------------


def test_an_empty_roster_proposes_empty_groups_without_rejecting() -> None:
    proposal = suggest_groups([], group_count=2)
    assert proposal.rejected is None
    assert sizes(proposal) == [0, 0]


def test_groups_carry_order_for_consecutive_runs() -> None:
    proposal = suggest_groups(make_animals("MMMM"), group_count=2)
    assert [g.order for g in proposal.groups] == [0, 1]
    assert [g.name for g in proposal.groups] == ["Group 1", "Group 2"]
