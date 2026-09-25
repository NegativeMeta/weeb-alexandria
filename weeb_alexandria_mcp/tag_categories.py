"""Source-specific tag category names used by database importers."""
from __future__ import annotations


CATEGORY_NAMES_BY_SOURCE = {
    "danbooru": {
        "0": "general",
        "1": "artist",
        "3": "copyright",
        "4": "character",
        "5": "meta",
    },
    # The combined e621-derived export uses e621 category ids.
    "combined": {
        "0": "general",
        "1": "artist",
        "2": "contributor",
        "3": "copyright",
        "4": "character",
        "5": "species",
        "6": "invalid",
        "7": "meta",
        "8": "lore",
    },
    "gelbooru": {
        "0": "general",
        "1": "artist",
        "3": "copyright",
        "4": "character",
        "5": "meta",
        "6": "alias",  # Gelbooru deprecated/alias tags.
        "7": "meta",
    },
}


def category_name_for(source: str, category: str) -> str | None:
    """Translate a source-specific category id without mixing ID systems."""
    return CATEGORY_NAMES_BY_SOURCE.get(source, {}).get(category, category or None)
