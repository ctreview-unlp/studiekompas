"""
Shared helpers for interpreting scraped course data, used by both the
scraper (app/scripts/scrape_unlp_courses.py) and the system prompt
(app/prompts.py).

One course page on unlp.nl can list several variants of a course, each
with its own price (e.g. the "NLP Practitioner" page lists the 8-day
Intensief at €2750, the 15-day regular course at €2995 and the online
version at €1795). Prices therefore have to be read per variant, never as
one price per course page.
"""

import re

# A variant name as it appears at the top of an offer's price info, e.g.
# "Practitioner Intensief (8 dagen)", "NLP Practitioner Online (15 avonden)"
# or "NLP Master Practitioner Online". The same spot often holds general text
# instead ("Inclusief:", "Voor wie:", "Data, locatie en investering"), which
# is not a variant.
VARIANT_DURATION = re.compile(r"\(\s*\d+\s*(dagen|dag|avonden|avond|weken|modules?)\s*\)", re.IGNORECASE)
VARIANT_KEYWORD = re.compile(r"\b(online|intensief|intensive)\b", re.IGNORECASE)


def clean_variant(text: str | None) -> str | None:
    """Return the text if it names a course variant, otherwise None."""
    if not text:
        return None
    text = text.strip()
    if VARIANT_DURATION.search(text) or VARIANT_KEYWORD.search(text):
        return text
    return None


def format_price(price) -> str:
    return f"€ {float(price):.0f}"


def summarize_prices(offers: list[dict]) -> str | None:
    """
    One line describing the prices of a course's scheduled offers, grouped
    by variant: "€ 1099" when there is one price, otherwise e.g.
    "Practitioner Intensief (8 dagen): € 2750; NLP Practitioner (15 dagen): € 2995".
    Offers are dicts with "variant" and "price". Returns None without prices.
    """
    by_variant: dict[str | None, set[float]] = {}
    for offer in offers:
        if offer.get("price") is None:
            continue
        by_variant.setdefault(clean_variant(offer.get("variant")), set()).add(float(offer["price"]))
    if not by_variant:
        return None

    all_prices = {p for prices in by_variant.values() for p in prices}
    if len(all_prices) == 1:
        return format_price(next(iter(all_prices)))

    parts = []
    for variant, prices in sorted(by_variant.items(), key=lambda kv: min(kv[1])):
        label = variant or "andere data (zie prijs per datum)"
        amounts = " of ".join(format_price(p) for p in sorted(prices))
        parts.append(f"{label}: {amounts}")
    return "; ".join(parts)
