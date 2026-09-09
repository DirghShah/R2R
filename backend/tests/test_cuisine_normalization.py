"""Cuisines are a closed list.

Left open, the extractor produced "bakery", "patisserie", "café" and
"rotisserie" for what a user experiences as two or three things — which made
the map's filter chips useless and gave near-identical places different pin
colours. The tool schema asks for one of the list verbatim, but non-strict tool
use does not enforce that, so this normalisation is the actual guarantee.
"""
from __future__ import annotations

import pytest

from worker.extract import CUISINES, normalize_cuisine


def test_canonical_labels_pass_through_unchanged():
    for label in CUISINES:
        assert normalize_cuisine(label) == label


def test_matching_is_case_and_space_insensitive():
    assert normalize_cuisine("  ITALIAN ") == "Italian"
    assert normalize_cuisine("cafe / coffee") == "Cafe / Coffee"


@pytest.mark.parametrize("raw,expected", [
    ("café", "Cafe / Coffee"),
    ("coffee shop", "Cafe / Coffee"),
    ("patisserie", "Bakery"),
    ("gelato", "Dessert"),
    ("boba", "Tea / Boba"),
    ("cocktail bar", "Bar"),
    ("wine bar", "Bar"),
    ("ramen", "Japanese"),
    ("taqueria", "Mexican"),
    ("rotisserie", "American"),
    ("food truck", "Street Food / Food Truck"),
    ("vegan", "Vegetarian / Vegan"),
])
def test_the_labels_that_caused_the_mess_are_folded(raw, expected):
    assert normalize_cuisine(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Italian Restaurant", "Italian"),
    ("authentic thai food", "Thai"),
    ("Modern Japanese", "Japanese"),
])
def test_a_label_containing_a_canonical_name_is_snapped_to_it(raw, expected):
    assert normalize_cuisine(raw) == expected


def test_longer_names_win_over_substrings():
    """"Latin American" contains "American" — the specific one has to win, or
    every Latin place would be filed under American."""
    assert normalize_cuisine("Latin American") == "Latin American"
    assert normalize_cuisine("modern latin american") == "Latin American"


def test_anything_unrecognised_becomes_other():
    """Better one honest bucket than a one-off chip with a hashed colour."""
    assert normalize_cuisine("xyzzy") == "Other"
    assert normalize_cuisine("molecular gastronomy") == "Other"


def test_absent_stays_absent():
    """Non-food places (a hotel, a sight) legitimately have no cuisine."""
    assert normalize_cuisine(None) is None
    assert normalize_cuisine("   ") is None
