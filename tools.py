"""
tools.py

The FitFindr tools. Each tool is a standalone function that can be called
and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item, savings)      → str
    estimate_savings(item)                          → dict
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

_MODEL = "llama-3.3-70b-versatile"


def _chat(prompt: str, temperature: float = 0.7) -> str:
    """Send a single-user-message chat completion to Groq and return the text."""
    client = _get_groq_client()
    resp = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return resp.choices[0].message.content.strip()


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    # Tokenize the description into lowercase keywords for scoring.
    keywords = [w for w in re.findall(r"[a-z0-9]+", description.lower()) if len(w) > 1]

    scored: list[tuple[int, dict]] = []
    for item in listings:
        # --- price filter ---
        if max_price is not None and item["price"] > max_price:
            continue

        # --- size filter (loose, case-insensitive substring both ways) ---
        if size is not None:
            item_size = (item.get("size") or "").lower()
            wanted = size.lower()
            if wanted not in item_size and item_size not in wanted:
                continue

        # --- relevance score: keyword overlap across the searchable fields ---
        haystack = " ".join([
            item.get("title", ""),
            item.get("description", ""),
            item.get("category", ""),
            item.get("brand") or "",
            " ".join(item.get("style_tags", [])),
            " ".join(item.get("colors", [])),
        ]).lower()

        score = sum(1 for kw in keywords if kw in haystack)
        if score > 0:
            scored.append((score, item))

    # Highest score first; empty list if nothing matched (no exception).
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    title = new_item.get("title", "this piece")
    item_desc = (
        f"{title} "
        f"(category: {new_item.get('category', 'n/a')}, "
        f"colors: {', '.join(new_item.get('colors', [])) or 'n/a'}, "
        f"style: {', '.join(new_item.get('style_tags', [])) or 'n/a'})"
    )

    items = wardrobe.get("items", [])

    if not items:
        # Empty-wardrobe branch: general advice, no owned pieces to name.
        prompt = (
            f"A shopper is considering buying this secondhand item:\n{item_desc}\n\n"
            "They haven't told us what's in their closet. In 3-4 sentences, give practical "
            "general styling advice: what colors, bottoms/tops, shoes, and silhouettes pair "
            "well with it, and what overall vibe it suits. Be concrete, not generic."
        )
    else:
        wardrobe_lines = "\n".join(
            f"- {it['name']} ({it.get('category', '')}; "
            f"{', '.join(it.get('style_tags', []))})"
            for it in items
        )
        prompt = (
            f"A shopper is considering buying this secondhand item:\n{item_desc}\n\n"
            f"Here is what they already own:\n{wardrobe_lines}\n\n"
            "Suggest 1-2 complete outfits that pair the new item with pieces from THIS wardrobe. "
            "Name the specific owned pieces you'd use. Add one quick styling tip (tuck, roll, "
            "layer). Keep it to 3-5 sentences, casual and specific."
        )

    try:
        return _chat(prompt, temperature=0.7)
    except Exception:
        return (
            "Couldn't reach the styling model right now — try again in a moment. "
            f"In the meantime, {title} is a versatile piece worth building a simple, "
            "balanced outfit around."
        )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict, savings: dict | None = None) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.
        savings:  Optional dict from estimate_savings() — if provided and
                  savings_amount > 0, the caption may mention the deal.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)
    """
    # Guard: no outfit → descriptive error string, no LLM call, no exception.
    if not outfit or not outfit.strip():
        return "Can't write a fit card without an outfit suggestion."

    title = new_item.get("title", "this find")
    price = new_item.get("price")
    platform = new_item.get("platform", "a resale app")
    price_str = f"${price:.0f}" if isinstance(price, (int, float)) else "a steal"

    savings_line = ""
    if savings and savings.get("savings_amount", 0) > 0:
        savings_line = (
            f"\nEstimated retail price: ~${savings['estimated_retail']:.0f} "
            f"(saved ~${savings['savings_amount']:.0f}, about {savings['savings_pct']}% off)\n"
        )

    prompt = (
        "Write a short, casual social-media caption (2-4 sentences) for a thrifted outfit. "
        "It should read like a real OOTD/Instagram caption, NOT a product description.\n\n"
        f"Item: {title}\nPrice: {price_str}\nBought on: {platform}\n"
        f"How it's styled: {outfit}\n"
        f"{savings_line}\n"
        "Mention the item name, the price, and the platform naturally — once each. "
        "Capture the vibe in specific terms. Lowercase, a little playful, an emoji or two is fine. "
        + ("If a savings/deal line is given above, weave it in naturally (e.g. 'for way less than retail'). "
           if savings_line else "")
        + "Return only the caption."
    )

    try:
        # Higher temperature so captions vary run-to-run for the same input.
        return _chat(prompt, temperature=1.0)
    except Exception:
        return (
            f"thrifted {title} on {platform} for {price_str} and i'm obsessed — "
            "styled it exactly how i hoped ✨ (caption generator hiccuped, but the fit's real)"
        )


# ── Tool 4: estimate_savings ──────────────────────────────────────────────────

def estimate_savings(item: dict) -> dict:
    """
    Estimate the typical retail (new) price for an item and compute how much
    the user saves by buying it secondhand at its listed price.

    Args:
        item: A listing dict (the selected item) — uses title, brand,
              category, and price.

    Returns:
        A dict:
            {
                "estimated_retail": float,
                "savings_amount": float,  # estimated_retail - price, floored at 0
                "savings_pct": int,       # round(savings_amount / estimated_retail * 100)
            }
        Never raises. If the LLM call fails or its response can't be parsed
        into a usable number, falls back to a heuristic estimate
        (estimated_retail = price * 2.5).
    """
    price = item.get("price") or 0.0
    title = item.get("title", "this item")
    brand = item.get("brand") or "a generic/unbranded version"
    category = item.get("category", "clothing")

    prompt = (
        f"Estimate the typical retail price in USD for this item brand new, full price: "
        f"\"{title}\" (category: {category}, brand: {brand}).\n"
        "Respond with ONLY a number — no dollar sign, no words, no range."
    )

    estimated_retail = None
    try:
        response = _chat(prompt, temperature=0.3)
        match = re.search(r"\d+(?:\.\d+)?", response)
        if match:
            candidate = float(match.group(0))
            if candidate > price:
                estimated_retail = candidate
    except Exception:
        pass

    if estimated_retail is None:
        estimated_retail = price * 2.5

    savings_amount = max(0.0, estimated_retail - price)
    savings_pct = (
        round(savings_amount / estimated_retail * 100) if estimated_retail > 0 else 0
    )

    return {
        "estimated_retail": estimated_retail,
        "savings_amount": savings_amount,
        "savings_pct": savings_pct,
    }
