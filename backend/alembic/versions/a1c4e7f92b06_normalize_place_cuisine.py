"""Snap existing Place.cuisine values onto the closed list.

Cuisine used to be free text, so saved places carry labels like "bakery",
"patisserie", "café" and "rotisserie" — several strings for what a user
experiences as one thing. New analyses are normalised at extraction time, but
places analysed before that keep the old labels, which means stale filter chips
and grey fallback pin colours on maps people already have.

This is a data migration, so the mapping is inlined rather than imported from
worker.extract. A migration has to produce the same result years from now
regardless of how the application code has moved on.

Revision ID: a1c4e7f92b06
Revises: f7b3c8e21d94
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1c4e7f92b06"
down_revision = "f7b3c8e21d94"
branch_labels = None
depends_on = None

CUISINES = [
    "American", "Italian", "French", "Mexican", "Latin American", "Caribbean",
    "Chinese", "Japanese", "Korean", "Indian", "Thai", "Vietnamese",
    "Mediterranean", "Middle Eastern", "Greek", "Spanish", "African",
    "Southeast Asian", "Asian Fusion", "European",
    "Seafood", "Steakhouse", "Sushi", "Pizza", "BBQ", "Burgers",
    "Vegetarian / Vegan", "Deli / Sandwich",
    "Cafe / Coffee", "Bakery", "Dessert", "Juice / Smoothie", "Tea / Boba",
    "Bar", "Nightclub / Lounge",
    "Food Hall / Market", "Street Food / Food Truck", "Other",
]

ALIASES = {
    "cafe": "Cafe / Coffee", "café": "Cafe / Coffee", "coffee": "Cafe / Coffee",
    "coffee shop": "Cafe / Coffee", "espresso": "Cafe / Coffee",
    "patisserie": "Bakery", "pastry": "Bakery", "bakery / pastry": "Bakery",
    "ice cream": "Dessert", "gelato": "Dessert", "desserts": "Dessert",
    "boba": "Tea / Boba", "bubble tea": "Tea / Boba", "tea": "Tea / Boba",
    "smoothie": "Juice / Smoothie", "juice": "Juice / Smoothie",
    "cocktail bar": "Bar", "wine bar": "Bar", "brewery": "Bar", "pub": "Bar",
    "speakeasy": "Bar", "nightclub": "Nightclub / Lounge",
    "club": "Nightclub / Lounge", "lounge": "Nightclub / Lounge",
    "ramen": "Japanese", "izakaya": "Japanese", "yakitori": "Japanese",
    "taco": "Mexican", "tacos": "Mexican", "taqueria": "Mexican",
    "vegan": "Vegetarian / Vegan", "vegetarian": "Vegetarian / Vegan",
    "plant-based": "Vegetarian / Vegan",
    "deli": "Deli / Sandwich", "sandwiches": "Deli / Sandwich",
    "sandwich": "Deli / Sandwich", "bagels": "Deli / Sandwich",
    "food truck": "Street Food / Food Truck", "street food": "Street Food / Food Truck",
    "market": "Food Hall / Market", "food hall": "Food Hall / Market",
    "rotisserie": "American", "diner": "American", "brunch": "American",
    "breakfast": "American", "southern": "American", "soul food": "American",
    "asian": "Asian Fusion", "latin": "Latin American", "halal": "Middle Eastern",
    "turkish": "Middle Eastern", "lebanese": "Middle Eastern",
    "peruvian": "Latin American", "brazilian": "Latin American",
    "filipino": "Southeast Asian", "malaysian": "Southeast Asian",
    "indonesian": "Southeast Asian", "german": "European", "british": "European",
    "portuguese": "European", "ethiopian": "African", "moroccan": "African",
}

_BY_KEY = {c.lower(): c for c in CUISINES}


def _normalize(value: str) -> str:
    key = value.strip().lower()
    if key in _BY_KEY:
        return _BY_KEY[key]
    if key in ALIASES:
        return ALIASES[key]
    # Longest first, so "Latin American" isn't swallowed by "American".
    for canonical in sorted(CUISINES, key=len, reverse=True):
        if canonical.lower() in key:
            return canonical
    for alias, canonical in ALIASES.items():
        if alias in key:
            return canonical
    return "Other"


def upgrade() -> None:
    conn = op.get_bind()
    places = sa.table("places", sa.column("id", sa.String), sa.column("cuisine", sa.String))

    rows = conn.execute(
        sa.select(places.c.id, places.c.cuisine).where(places.c.cuisine.isnot(None))
    ).fetchall()

    changed = 0
    for place_id, cuisine in rows:
        if not cuisine or not cuisine.strip():
            continue
        canonical = _normalize(cuisine)
        if canonical != cuisine:
            conn.execute(
                places.update().where(places.c.id == place_id).values(cuisine=canonical)
            )
            changed += 1
    print(f"[migration] normalised {changed} of {len(rows)} place cuisines")


def downgrade() -> None:
    # One-way: the original free-text labels aren't recoverable, and they were
    # the problem. Nothing depends on getting them back.
    pass
