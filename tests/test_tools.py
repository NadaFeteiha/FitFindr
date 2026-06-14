"""
Tool tests for FitFindr.

Run from the repo root with:
    pytest tests/

The search_listings tests are pure (no network). The LLM-backed tools
(suggest_outfit, create_fit_card) are tested for their *failure modes*, which
do not require a network call, plus a guarded live test that is skipped if no
GROQ_API_KEY is present.
"""

import os

import pytest

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── search_listings ─────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # Impossible combination → empty list, NOT an exception.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_sorted_by_relevance():
    results = search_listings("vintage denim", size=None, max_price=None)
    # Every returned item should be relevant (score > 0 means at least one
    # keyword appears somewhere in its searchable fields).
    assert len(results) > 0


# ── create_fit_card failure mode (no network needed) ─────────────────────────

def test_fit_card_empty_outfit_returns_error_string():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = create_fit_card("", item)
    assert isinstance(result, str)
    assert "without an outfit" in result.lower()


def test_fit_card_whitespace_outfit_returns_error_string():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = create_fit_card("   ", item)
    assert isinstance(result, str)
    assert result == "Can't write a fit card without an outfit suggestion."


# ── live LLM tests (skipped without an API key) ──────────────────────────────

_HAS_KEY = bool(os.environ.get("GROQ_API_KEY"))


@pytest.mark.skipif(not _HAS_KEY, reason="GROQ_API_KEY not set")
def test_suggest_outfit_empty_wardrobe_returns_nonempty():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = suggest_outfit(item, get_empty_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""


@pytest.mark.skipif(not _HAS_KEY, reason="GROQ_API_KEY not set")
def test_suggest_outfit_with_wardrobe_returns_nonempty():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = suggest_outfit(item, get_example_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""
