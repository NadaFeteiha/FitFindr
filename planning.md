# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## What FitFindr Does (in 2–3 sentences)

FitFindr takes a natural-language thrifting request (e.g. *"vintage graphic tee under $30, size M"*),
parses out a description, size, and price ceiling, then searches a mock secondhand-listings dataset
for matching items. If it finds something, it picks the best match, suggests how to style it against
the user's existing wardrobe, and writes a short shareable "fit card" caption. If the search returns
nothing, it stops early and tells the user exactly what to loosen (price, size, or keywords) instead
of calling the styling tools with empty input.

---

## Tools

### Tool 1: search_listings

**What it does:**
Filters the 40-item mock listings dataset by an optional size and price ceiling, then ranks the
survivors by keyword overlap with the user's description and returns the matches best-first.

**Input parameters:**
- `description` (str): Free-text keywords describing the desired item, e.g. `"vintage graphic tee"`. Tokenized and matched against each listing's title, description, style_tags, category, brand, and colors.
- `size` (str | None): Size to filter by, e.g. `"M"`. Matched case-insensitively as a substring so `"M"` matches `"S/M"`. `None` skips size filtering.
- `max_price` (float | None): Inclusive price ceiling. `None` skips price filtering.

**What it returns:**
A `list[dict]` of matching listings, sorted by relevance score (highest first). Each dict has the
dataset fields: `id, title, description, category, style_tags (list), size, condition, price (float),
colors (list), brand, platform`. Listings with a keyword-overlap score of 0 are dropped.

**What happens if it fails or returns nothing:**
Returns an empty list `[]` (never raises). The planning loop detects the empty list, sets a helpful
`session["error"]` telling the user which constraints to loosen, and returns early — it does NOT call
suggest_outfit with empty input.

---

### Tool 2: suggest_outfit

**What it does:**
Uses the LLM (Groq `llama-3.3-70b-versatile`) to suggest 1–2 complete outfit combinations that pair
the newly found item with pieces the user already owns.

**Input parameters:**
- `new_item` (dict): A listing dict (the item the user is considering), used for its title, category, colors, and style_tags.
- `wardrobe` (dict): A wardrobe dict with an `items` key (list of wardrobe-item dicts: `id, name, category, colors, style_tags, notes`). May be empty.

**What it returns:**
A non-empty `str` of styling advice — concrete outfit combos naming specific wardrobe pieces when the
wardrobe is non-empty, or general styling ideas (what colors/silhouettes pair well, what vibe it suits)
when the wardrobe is empty.

**What happens if it fails or returns nothing:**
- Empty wardrobe → prompts the LLM for general styling advice instead of crashing.
- LLM/network error → caught and returned as a readable fallback string ("Couldn't reach the styling
  model — try again in a moment.") so the agent stays usable.

---

### Tool 3: create_fit_card

**What it does:**
Uses the LLM at a higher temperature to write a short, casual, shareable caption (the kind you'd put on
an OOTD post) for the found item styled per the outfit suggestion.

**Input parameters:**
- `outfit` (str): The outfit-suggestion string returned by `suggest_outfit`.
- `new_item` (dict): The listing dict, used to mention the item title, price, and platform naturally.

**What it returns:**
A 2–4 sentence `str` caption that mentions the item name, price, and platform once each, captures the
outfit vibe, and reads like a real social caption — varying run-to-run because temperature is high.

**What happens if it fails or returns nothing:**
- Empty / whitespace-only `outfit` → returns a descriptive error string (no LLM call, no exception):
  `"Can't write a fit card without an outfit suggestion."`
- LLM/network error → caught and returned as a readable fallback string.

---

### Additional Tools (if any)

### Tool 4: estimate_savings (stretch)

**What it does:**
Uses the LLM to estimate the typical retail (new) price for an item like `new_item`, then computes how
much the user saves by buying it secondhand at its listed price.

**Input parameters:**
- `item` (dict): A listing dict (the selected item), used for its title, brand, category, and price.

**What it returns:**
A `dict`:
```python
{
    "estimated_retail": float,
    "savings_amount": float,   # estimated_retail - item["price"], floored at 0
    "savings_pct": int,        # round(savings_amount / estimated_retail * 100), floored at 0
}
```

**What happens if it fails or returns nothing:**
LLM/network error or unparsable response → falls back to a heuristic estimate
(`estimated_retail = item["price"] * 2.5`) and computes the same dict from that — never raises, never
returns `None`.

---

## Planning Loop

**How does your agent decide which tool to call next?**

`run_agent(query, wardrobe)` runs a single linear-with-branches loop over a `session` dict. Its behavior
changes based on what each tool returns — it is NOT a fixed "always call all three" sequence:

1. **Parse.** Extract `description`, `size`, `max_price` from `query` with regex:
   - `max_price`: regex `under \$?(\d+)` or `\$(\d+)` → float; else `None`.
   - `size`: regex `size\s+(\w+)` or `\bin (\w+)\b` patterns; else `None`.
   - `description`: the query with the matched price/size phrases stripped out.
   Store in `session["parsed"]`.
2. **Search.** Call `search_listings(description, size, max_price)`; store in `session["search_results"]`.
3. **Branch on the result (this is the decision point) — with retry-on-empty (stretch):**
   - **If `search_results` is non-empty** → set `session["selected_item"] = search_results[0]`,
     `session["relaxed"] = None`, and continue.
   - **If `search_results` is empty** → retry with progressively looser constraints, in this fixed
     order, stopping at the first attempt that returns non-empty results:
     1. *(only if `size` was set)* drop size: `search_listings(description, None, max_price)`.
     2. *(only if `max_price` was set)* raise the ceiling 50%: `search_listings(description, size, max_price * 1.5)`.
     3. *(only if both were set and 1–2 still empty)* drop size AND raise the ceiling 50%:
        `search_listings(description, None, max_price * 1.5)`.
     - The first retry attempt that succeeds sets `session["search_results"]`,
       `session["selected_item"] = search_results[0]`, and `session["relaxed"]` to a short string
       describing what changed (e.g. `"dropped your size filter"`, `"raised your price ceiling to ~$45"`,
       `"dropped your size filter and raised your price ceiling to ~$45"`). The loop then continues to
       step 4 as normal.
     - **If all attempts (original + retries) are empty** → set `session["error"]` to a message naming
       what to loosen, leave `outfit_suggestion`/`fit_card`/`savings` as `None`, and **return early**.
       suggest_outfit is never called.
4. **Estimate savings (stretch).** Call `estimate_savings(selected_item)`; store in `session["savings"]`.
5. **Suggest.** Call `suggest_outfit(selected_item, wardrobe)`; store in `session["outfit_suggestion"]`.
6. **Fit card.** Call `create_fit_card(outfit_suggestion, selected_item, savings)`; store in
   `session["fit_card"]`.
7. **Return** the completed session.

The loop "knows it's done" when it either hits the early-return error branch or finishes step 6 with all
session fields populated.

---

## State Management

**How does information from one tool get passed to the next?**

A single `session` dict (created by `_new_session`) is the one source of truth for the interaction. It is
created once at the top of `run_agent` and threaded through every step:

- `query` / `parsed` — raw input and extracted `description`/`size`/`max_price`.
- `search_results` — output of tool 1 (from whichever attempt — original or a retry — first succeeded).
- `relaxed` — `None` if the original search succeeded; otherwise a short string describing which
  constraint(s) the retry loop dropped/loosened to find results.
- `selected_item` — `search_results[0]`; this exact dict is passed into `estimate_savings`,
  `suggest_outfit`, and `create_fit_card`, so the item the user re-searches for never has to be re-entered.
- `savings` — output of tool 4 (`estimate_savings`); passed into `create_fit_card`.
- `outfit_suggestion` — output of tool 2; passed directly into tool 3.
- `fit_card` — output of tool 3.
- `error` — set only on the early-return branch (all search attempts empty); `None` on success.

Each tool reads from the session and writes its result back before the next tool runs, so no value is
re-derived or re-entered between steps. `app.py` reads the final session and maps three of its fields to
the three output panels.

---

## Error Handling

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Agent retries with progressively looser constraints (drop size, then raise price ceiling 50%, then both — see Planning Loop). If a retry succeeds, `session["relaxed"]` explains what changed and the loop continues normally. If **all** attempts are empty, sets `session["error"]`: *"No listings matched 'X' under $Y in size Z. Try raising your price, dropping the size filter, or using broader keywords."* and stops — does not call the styling tools. |
| estimate_savings | LLM/network error or unparsable response | Falls back to a heuristic (`estimated_retail = price * 2.5`) and computes `savings_amount`/`savings_pct` from that — never raises. |
| suggest_outfit | Wardrobe is empty | Tool detects `wardrobe["items"] == []` and asks the LLM for general styling advice for the item (colors/silhouettes/vibe) instead of naming owned pieces; still returns a useful non-empty string. |
| suggest_outfit | LLM/network error | Caught; returns a readable fallback string so the agent doesn't crash. |
| create_fit_card | Outfit input is missing or incomplete | Returns the descriptive string *"Can't write a fit card without an outfit suggestion."* with no LLM call and no exception. |

---

## Architecture

```
User query + wardrobe choice
        │
        ▼
┌──────────────────────────────────────────────────────────────────┐
│  run_agent()  — Planning Loop                                      │
│                                                                    │
│  parse query (regex) ──► session["parsed"] {description,size,max_price}
│        │                                                           │
│        ▼                                                           │
│  search_listings(description, size, max_price)                     │
│        │                                                           │
│        ├── results == []  ──► retry: drop size ──► raise price 50% │
│        │                          ──► drop size + raise price       │
│        │                                                           │
│        │     ├── all retries == [] ──► session["error"] = "loosen..."
│        │     │                         └─► RETURN early (fit_card/savings stay None)
│        │     │                                                     │
│        │     └── a retry succeeds ──► session["relaxed"] = "dropped size..."
│        │                                                           │
│        │ results == [item, ...] (original or relaxed)              │
│        ▼                                                           │
│  session["selected_item"] = results[0]                             │
│        │                                                           │
│        ▼                                                           │
│  estimate_savings(selected_item)                                    │
│        │   (LLM error ► heuristic 2.5x fallback inside tool)       │
│        ▼                                                           │
│  session["savings"] = {estimated_retail, savings_amount, savings_pct}
│        │                                                           │
│        ▼                                                           │
│  suggest_outfit(selected_item, wardrobe)                            │
│        │   (empty wardrobe ► general advice branch inside tool)    │
│        ▼                                                           │
│  session["outfit_suggestion"] = "..."                              │
│        │                                                           │
│        ▼                                                           │
│  create_fit_card(outfit_suggestion, selected_item, savings)        │
│        │   (empty outfit ► error-string branch inside tool)        │
│        ▼                                                           │
│  session["fit_card"] = "..."                                       │
│        │                                                           │
└────────┼─────────────────────────────────────────────────────────┘
         ▼
   return session  ──►  app.py maps fields to 3 output panels + relaxed notice
```

State store = the `session` dict, read/written at every step above.

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**
- **Tool:** Claude (Claude Code in the IDE).
- **Input I'll give it:** the Tool 1 / Tool 2 / Tool 3 spec blocks above (inputs, return value, failure
  mode), one tool at a time, plus the instruction to use `load_listings()` for tool 1 and Groq
  `llama-3.3-70b-versatile` for tools 2–3.
- **Expected output:** each function implemented in `tools.py` with the exact signatures already stubbed.
- **How I'll verify:** read each function against its spec (does it filter by all three params? does it
  handle the empty-result / empty-wardrobe / empty-outfit case?), then run `pytest tests/` plus 3 manual
  queries before trusting it.

**Milestone 4 — Planning loop and state management:**
- **Tool:** Claude.
- **Input I'll give it:** the Architecture diagram above + the Planning Loop and State Management sections.
- **Expected output:** `run_agent()` implementing the parse → search → branch → suggest → fit-card flow,
  storing each result in `session`, and `handle_query()` mapping the session to the 3 panels.
- **How I'll verify:** confirm it branches on the empty-search result (no unconditional calls), then run
  `python agent.py` and check the no-results path leaves `fit_card = None` while the happy path fills all three.

---

## A Complete Interaction (Step by Step)

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1 — Parse & Search:**
`run_agent` parses → `description="vintage graphic tee ..."`, `size=None`, `max_price=30.0`.
Calls `search_listings("vintage graphic tee", size=None, max_price=30.0)`. Listings over $30 are
dropped; survivors are scored on keyword overlap ("vintage", "graphic", "tee"). Returns a ranked list,
e.g. top result the Y2K Baby Tee / a faded band tee at ~$18–22. `session["selected_item"] = results[0]`.

**Step 2 — Suggest outfit:**
Calls `suggest_outfit(selected_item, example_wardrobe)`. The LLM sees the tee plus the user's baggy
straight-leg jeans, wide-leg trousers, chunky white sneakers, and combat boots, and returns something
like: *"Pair it with your baggy straight-leg jeans and chunky white sneakers for an easy 90s look —
half-tuck the front for shape, and throw the black denim jacket over it when it's cold."*
`session["outfit_suggestion"]` is set.

**Step 3 — Fit card:**
Calls `create_fit_card(outfit_suggestion, selected_item)`. Returns a caption like: *"found this vintage
tee on depop for $18 and it was made for my baggy jeans 🖤 half-tucked it with the chunky sneakers, full
fit in stories."* `session["fit_card"]` is set.

**Final output to user:**
The Gradio UI shows three panels — the top listing (title, price, condition, platform), the outfit idea,
and the fit card caption.

---

## Stretch (update before starting)

**Implemented — Retry with loosened constraints.** If `search_listings` returns `[]`, the loop retries
with progressively looser constraints in a fixed order (drop size → raise price ceiling 50% → drop size
AND raise price 50%), stopping at the first non-empty result. `session["relaxed"]` is set to a short
string describing what changed; `app.py` shows it as a small notice above the listing. If every attempt
(original + all retries) is empty, the original error behavior is unchanged. See Planning Loop and
Architecture above for the exact order and Error Handling for the failure-mode table.

**Implemented — Tool 4: estimate_savings.** A new tool that estimates an item's retail price via the LLM
and computes savings vs. its secondhand price (falling back to a 2.5x heuristic on LLM failure). Wired
into the planning loop after `selected_item` is chosen; `session["savings"]` is passed into
`create_fit_card` so the caption can mention the deal. See Tool 4 spec above.
