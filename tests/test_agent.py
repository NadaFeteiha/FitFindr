"""
Agent / planning-loop tests for FitFindr.

These tests don't require GROQ_API_KEY: suggest_outfit and create_fit_card
fall back to readable placeholder strings when the LLM is unreachable, so
run_agent still completes its full session shape without a live key.
"""

from agent import _search_with_retries, run_agent
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── _search_with_retries ──────────────────────────────────────────────────────

def test_retry_drops_size_when_it_excludes_everything():
    # "track jacket" only matches size-M/M-L items, so size="XL" excludes
    # all of them on the first attempt.
    parsed = {"description": "track jacket", "size": "XL", "max_price": 50}
    results, relaxed = _search_with_retries(parsed)

    assert results  # second attempt (size dropped) should find matches
    assert relaxed == "dropped your size filter"


def test_retry_raises_price_ceiling_when_only_match_is_pricier():
    # "bomber" matches exactly one $75 item; max_price=50 excludes it
    # originally but $50 * 1.5 = $75 includes it.
    parsed = {"description": "bomber", "size": None, "max_price": 50}
    results, relaxed = _search_with_retries(parsed)

    assert results
    assert relaxed == "raised your price ceiling to ~$75"


def test_retry_no_relaxation_needed_when_original_succeeds():
    parsed = {"description": "vintage graphic tee", "size": None, "max_price": 50}
    results, relaxed = _search_with_retries(parsed)

    assert results
    assert relaxed is None


def test_retry_all_attempts_empty_for_impossible_query():
    parsed = {"description": "designer ballgown", "size": "XXS", "max_price": 5}
    results, relaxed = _search_with_retries(parsed)

    assert results == []
    assert relaxed is None


# ── run_agent ────────────────────────────────────────────────────────────────

def test_run_agent_happy_path_populates_full_session():
    session = run_agent(
        query="vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )

    assert session["error"] is None
    assert session["relaxed"] is None
    assert session["selected_item"] is not None
    assert session["savings"]["estimated_retail"] > 0
    assert session["savings"]["savings_amount"] >= 0
    assert 0 <= session["savings"]["savings_pct"] <= 100
    assert session["outfit_suggestion"]
    assert session["fit_card"]


def test_run_agent_relaxes_constraints_instead_of_erroring():
    session = run_agent(
        query="track jacket under $50, size XL",
        wardrobe=get_example_wardrobe(),
    )

    assert session["error"] is None
    assert session["relaxed"] == "dropped your size filter"
    assert session["selected_item"] is not None
    assert session["fit_card"]


def test_run_agent_no_results_leaves_downstream_fields_none():
    session = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )

    assert session["error"] is not None
    assert session["relaxed"] is None
    assert session["selected_item"] is None
    assert session["savings"] is None
    assert session["outfit_suggestion"] is None
    assert session["fit_card"] is None


def test_run_agent_works_with_empty_wardrobe():
    session = run_agent(
        query="vintage graphic tee under $30",
        wardrobe=get_empty_wardrobe(),
    )

    assert session["error"] is None
    assert session["outfit_suggestion"]
    assert session["fit_card"]
