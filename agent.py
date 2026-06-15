"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card, estimate_savings


# ── query parsing ─────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """
    Extract a description, size, and max_price from a free-text query using regex.

    Returns a dict: {"description": str, "size": str | None, "max_price": float | None}
    The description is the original query with the matched price/size phrases removed.
    """
    text = query.strip()

    # max_price: "under $30", "under 30", or a bare "$30"
    max_price = None
    price_match = re.search(r"(?:under|below|less than)\s*\$?\s*(\d+(?:\.\d+)?)", text, re.I)
    if not price_match:
        price_match = re.search(r"\$\s*(\d+(?:\.\d+)?)", text)
    if price_match:
        max_price = float(price_match.group(1))

    # size: "size M", "size 8", or "in a M" / "in M"
    size = None
    size_match = re.search(r"size\s+([a-z0-9/]+)", text, re.I)
    if not size_match:
        size_match = re.search(r"\bin\s+(?:a\s+)?(xs|s|m|l|xl|xxl|\d+)\b", text, re.I)
    if size_match:
        size = size_match.group(1).upper()

    # description: strip the matched price/size phrases so they don't pollute keywords
    description = text
    if price_match:
        description = description.replace(price_match.group(0), " ")
    if size_match:
        description = description.replace(size_match.group(0), " ")
    description = re.sub(r"\s+", " ", description).strip()

    return {"description": description, "size": size, "max_price": max_price}


# ── search with retry ────────────────────────────────────────────────────────

def _search_with_retries(parsed: dict) -> tuple[list[dict], str | None]:
    """
    Run search_listings with the parsed parameters. If that returns nothing,
    retry with progressively looser constraints until one attempt succeeds
    or all attempts are exhausted.

    Retry order (each only tried if applicable):
        1. Drop size (if size was set).
        2. Raise the price ceiling 50% (if max_price was set).
        3. Drop size AND raise the price ceiling 50% (if both were set and
           attempts 1-2 were still empty).

    Returns:
        (results, relaxed) — `relaxed` is None if the original search
        succeeded, otherwise a short string describing what was loosened
        for the attempt that finally returned results. If every attempt is
        empty, returns ([], None).
    """
    description = parsed["description"]
    size = parsed["size"]
    max_price = parsed["max_price"]

    results = search_listings(description, size, max_price)
    if results:
        return results, None

    attempts: list[tuple[str | None, float | None, str]] = []
    if size is not None:
        attempts.append((None, max_price, "dropped your size filter"))
    if max_price is not None:
        raised_price = max_price * 1.5
        attempts.append(
            (size, raised_price, f"raised your price ceiling to ~${raised_price:.0f}")
        )
        if size is not None:
            attempts.append((
                None,
                raised_price,
                f"dropped your size filter and raised your price ceiling to ~${raised_price:.0f}",
            ))

    for try_size, try_price, note in attempts:
        results = search_listings(description, try_size, try_price)
        if results:
            return results, note

    return [], None


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "relaxed": None,             # set if a retry with looser constraints succeeded
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "savings": None,             # dict returned by estimate_savings
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    Planning loop (see planning.md for the full spec):

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the query into description / size / max_price with
                _parse_query(). Store the result in session["parsed"].

        Step 3: Call _search_with_retries(), which runs search_listings() and,
                if that returns nothing, retries with progressively looser
                constraints (drop size, raise price 50%, both). Stores
                session["search_results"] and session["relaxed"] (a note on
                what was loosened, or None). If every attempt is empty, set
                session["error"] and return early — suggest_outfit and
                create_fit_card are NOT called with empty input.

        Step 4: Select the item to use (the top result). Store it in
                session["selected_item"].

        Step 5: Call estimate_savings() with the selected item.
                Store the result in session["savings"].

        Step 6: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 7: Call create_fit_card() with the outfit suggestion, selected
                item, and savings. Store the result in session["fit_card"].

        Step 8: Return the session.
    """
    # Step 1: fresh session — single source of truth for this interaction.
    session = _new_session(query, wardrobe)

    # Step 2: parse the query into search parameters.
    session["parsed"] = _parse_query(query)
    parsed = session["parsed"]

    # Step 3: search, retrying with looser constraints if the original is empty.
    session["search_results"], session["relaxed"] = _search_with_retries(parsed)

    # Step 3 (branch): no results from any attempt → set a helpful error and
    # return early. The styling tools are NOT called with empty input.
    if not session["search_results"]:
        bits = [f"'{parsed['description']}'"]
        if parsed["size"]:
            bits.append(f"in size {parsed['size']}")
        if parsed["max_price"] is not None:
            bits.append(f"under ${parsed['max_price']:.0f}")
        session["error"] = (
            f"No listings matched {' '.join(bits)}. "
            "Try raising your price, dropping the size filter, or using broader keywords."
        )
        return session

    # Step 4: select the top (most relevant) result.
    session["selected_item"] = session["search_results"][0]

    # Step 5: estimate how much the item saves vs. buying it new.
    session["savings"] = estimate_savings(session["selected_item"])

    # Step 6: suggest an outfit using the selected item + the user's wardrobe.
    session["outfit_suggestion"] = suggest_outfit(
        session["selected_item"], session["wardrobe"]
    )

    # Step 7: turn the outfit into a shareable fit card.
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"], session["selected_item"], session["savings"]
    )

    # Step 8: return the completed session.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
