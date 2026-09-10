"""One city per city.

The city on a place is free text — whatever the model wrote or the geocoder
returned — and both are inconsistent about the same place. A single New York map
turned into six lists in the app: "New York, NY", "Brooklyn, NY", "Long Island
City, NY", "Manhattan, NY", "New York" and "New York City, NY".
"""
from __future__ import annotations

import pytest

from worker.geocode import normalize_city


@pytest.mark.parametrize("raw", [
    "New York", "New York City", "NYC", "new york city", "  New York  ",
])
def test_the_spellings_of_new_york_are_one_city(raw):
    assert normalize_city(raw) == "New York"


@pytest.mark.parametrize("borough", [
    "Manhattan", "Brooklyn", "Queens", "The Bronx", "Staten Island",
    "Long Island City", "Astoria", "Williamsburg", "Harlem",
])
def test_the_boroughs_are_new_york(borough):
    assert normalize_city(borough, "NY") == "New York"


def test_an_appended_region_is_not_part_of_the_name():
    """"Austin" and "Austin, TX" were two cities; the region is its own column."""
    assert normalize_city("Austin, TX") == "Austin"
    assert normalize_city("Paris, France") == "Paris"


def test_an_ambiguous_name_outside_new_york_is_left_alone():
    """Manhattan, Kansas is a real place and not a borough."""
    assert normalize_city("Manhattan", "KS") == "Manhattan"
    assert normalize_city("Brooklyn", "OH") == "Brooklyn"


def test_a_city_we_know_nothing_about_survives_untouched():
    assert normalize_city("Lisbon") == "Lisbon"
    assert normalize_city("São Paulo") == "São Paulo"


def test_nothing_in_nothing_out():
    assert normalize_city(None) is None
    assert normalize_city("") is None
    assert normalize_city("   ") is None
    assert normalize_city(" , ") is None
