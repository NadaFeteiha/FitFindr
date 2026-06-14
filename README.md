# FitFindr 🛍️

FitFindr is a multi-tool AI agent that helps you find secondhand clothing and figure out how to wear it.
You describe what you want in plain language ("vintage graphic tee under $30, size M"); the agent searches
a mock listings dataset, suggests how to style the best match against your existing wardrobe, and writes a
short shareable "fit card" caption — handling the cases where a tool returns nothing or breaks.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Mac/Linux
pip install -r requirements.txt
```

Add your Groq API key to a `.env` file in the repo root (free key at [console.groq.com](https://console.groq.com)):

```
GROQ_API_KEY=your_key_here
```

## Run

```bash
python app.py          # Gradio UI — open the localhost URL it prints (usually http://localhost:7860)
python agent.py        # CLI: runs the happy path + the no-results path
pytest tests/          # runs the tool tests
```

LLM: Groq `llama-3.3-70b-versatile`.

---

## Tool Inventory

| Tool | Inputs | Output | Purpose |
|------|--------|--------|---------|
| `search_listings` | `description` (str), `size` (str \| None), `max_price` (float \| None) | `list[dict]` — matching listings sorted best-first (each dict: `id, title, description, category, style_tags, size, condition, price, colors, brand, platform`); `[]` if none match | Filter + rank the 40-item listings dataset against the user's request. |
| `suggest_outfit` | `new_item` (dict — a listing), `wardrobe` (dict with an `items` list) | `str` — 1–2 outfit ideas (names owned pieces if the wardrobe is non-empty; general advice if empty) | Style the found item against what the user already owns. |
| `create_fit_card` | `outfit` (str), `new_item` (dict — a listing) | `str` — a 2–4 sentence shareable caption (mentions item name, price, platform once each) | Turn the outfit into an OOTD-style social caption. |

`search_listings` is pure Python; `suggest_outfit` and `create_fit_card` call the Groq LLM.
Signatures match `tools.py` exactly.

## How the Planning Loop Works

`run_agent(query, wardrobe)` in [agent.py](agent.py) drives a single interaction. It is **not** a fixed
"always call all three tools" sequence — its path changes based on what `search_listings` returns:

1. **Parse** the query with regex (`_parse_query`) into `description`, `size`, and `max_price`. Price comes
   from patterns like `under $30`; size from `size M` / `in a M`; the description is the query with those
   phrases stripped so they don't pollute the keyword match.
2. **Search:** call `search_listings(description, size, max_price)`.
3. **Branch — the decision point:**
   - If the result list is **empty** → set `session["error"]` to a message naming exactly what to loosen
     (price / size / keywords) and **return early**. `suggest_outfit` and `create_fit_card` are never called,
     so `fit_card` stays `None`.
   - If **non-empty** → set `selected_item = results[0]` and continue.
4. **Suggest:** call `suggest_outfit(selected_item, wardrobe)`.
5. **Fit card:** call `create_fit_card(outfit_suggestion, selected_item)`.
6. **Return** the session.

So the agent's behavior genuinely differs by input: an impossible query stops after step 2 with an error;
a good query runs all the way through to a fit card.

## State Management

A single `session` dict (built by `_new_session`) is the source of truth for one interaction. It's created
once at the top of `run_agent` and threaded through every step — nothing is re-entered or re-derived:

| Field | Set when | Used by |
|-------|----------|---------|
| `query`, `parsed` | start / step 1 | search |
| `search_results` | step 2 | branch decision |
| `selected_item` | step 4 (`= search_results[0]`) | **passed into both** `suggest_outfit` and `create_fit_card` |
| `outfit_suggestion` | step 5 | passed into `create_fit_card` |
| `fit_card` | step 6 | shown to user |
| `error` | only on the early-return branch | shown to user; `None` on success |

The item found by `search_listings` flows into the styling tools automatically via `selected_item` — the
user never re-types it. `app.py`'s `handle_query` reads the final session and maps three fields to the three UI panels.

## Error Handling (per tool)

| Tool | Failure mode | What the agent does |
|------|--------------|---------------------|
| `search_listings` | No listings match | Returns `[]` (never raises). The loop catches it and sets a specific message, e.g. *"No listings matched 'designer ballgown' in size XXS under $5. Try raising your price, dropping the size filter, or using broader keywords."* — then stops without calling the styling tools. |
| `suggest_outfit` | Wardrobe is empty | Detects `wardrobe["items"] == []` and asks the LLM for general styling advice (colors / silhouettes / vibe) instead of naming owned pieces. Still returns a useful non-empty string. |
| `suggest_outfit` | LLM / network error | Wrapped in try/except; returns a readable fallback string so the agent stays usable. |
| `create_fit_card` | Outfit string empty/whitespace | Returns `"Can't write a fit card without an outfit suggestion."` — no LLM call, no exception. |

**Concrete example from testing:** running the bundled no-results query
`search_listings('designer ballgown', size='XXS', max_price=5)` returns `[]`; the full agent then responds
with the loosening message above and leaves `fit_card = None` — verified via `python agent.py`.

## Spec Reflection

- **How the spec helped:** writing the planning loop in `planning.md` as explicit branches (*"if results is
  empty, set error and return early; else select results[0]"*) meant `run_agent` was almost a transcription
  of the spec — the branch structure was decided before any code, which kept the agent from degenerating into
  an unconditional three-call pipeline.
- **Where implementation diverged:** the spec didn't anticipate how messy the dataset's `size` field is
  (`"S/M"`, `"W30 L30"`, bare numbers). Exact-match size filtering would have returned nothing for most
  queries, so the implemented filter uses a **two-way case-insensitive substring match** (`"M"` matches
  `"S/M"`). The spec was updated to describe this.

## AI Usage

1. **Implementing the three tools (Milestone 3).** I gave Claude the Tool 1–3 spec blocks from
   `planning.md` (inputs, return value, failure mode) one at a time and asked it to implement them in
   `tools.py` using `load_listings()` and Groq `llama-3.3-70b-versatile`. I reviewed each function against
   its spec and **changed the size filter** from exact equality to a two-way substring match after seeing
   that dataset sizes like `"S/M"` and `"W30 L30"` would otherwise filter everything out, then confirmed all
   `pytest tests/` cases passed.
2. **Implementing the planning loop (Milestone 4).** I gave Claude the Architecture diagram plus the Planning
   Loop and State Management sections and asked it to implement `run_agent`. I verified it **branches on the
   empty-search result** (rather than calling all three tools unconditionally) and stores each result in the
   `session` dict; I also **added the `_parse_query` regex helper** for size/price extraction, which the loop
   spec referenced but didn't fully specify.

## Project Layout

```
fitfindr/
├── data/                  listings.json (40 listings) + wardrobe_schema.json
├── utils/data_loader.py   load_listings / get_example_wardrobe / get_empty_wardrobe
├── tools.py               the 3 tools
├── agent.py               run_agent planning loop + _parse_query
├── app.py                 Gradio UI + handle_query
├── tests/test_tools.py    pytest tool tests
└── planning.md            spec (written before implementation)
```
