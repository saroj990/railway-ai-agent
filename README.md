# Rail Info Assistant

A small, chat-based AI agent that answers questions about Indian Railways trains using an
imported timetable, not model memory.

> **Independent project.** This is not an official Indian Railways, IRCTC or NTES service.
> It uses a stale, publicly published timetable (2017). It has **no live running status, no
> fares, no seat availability and no booking**.

The agent can:

- search direct trains between two stations for a journey date,
- show a full stop-by-stop schedule, route and timings,
- compare trains on a route by departure, arrival, duration, stops and distance,
- answer follow-up questions such as "which stations does it stop at?",
- explain clearly when the data does not contain something.

The LLM never supplies railway facts. It chooses tools and explains their output; every
number in an answer comes from the imported dataset.

---

## 1. Architecture and data flow

```
                      ┌──────────────────────────┐
  CSV timetable ─────►│ scripts/import_timetable │──► SQLite (trains, stations, train_stops, meta)
  (data.gov.in)       └──────────────────────────┘
                                                          │
                                                          ▼
  Browser ──► FastAPI ──► Agent ──► allowlisted tools ──► RailwayProvider ──► SQLite
   (chat UI)   /chat      │                         (LocalTimetableProvider)
                           │
                           ▼
                    LLMProvider
              ┌─────────────┴──────────────┐
        OllamaProvider            OpenAICompatibleProvider
                                   (future/optional)
```

| Layer | Where | Responsibility |
|---|---|---|
| UI | `app/static/` | Chat, tables, source/freshness display |
| API | `app/api.py` | `POST /chat`, `GET /health`, validation, safe errors |
| Agent | `app/agent.py` | System prompt, tool loop, allowlist, deterministic data caveat |
| LLM adapter | `app/llm/` | Ollama and OpenAI-compatible providers behind one interface |
| Tools | `app/tools/railway.py` | JSON schemas, argument validation, typed results |
| Railway provider | `app/providers/local.py` | Station resolution, search, schedules, comparisons |
| Data | `app/db.py`, `scripts/import_timetable.py` | SQLite schema and offline importer |

**Data flow for one question**

1. The browser posts a message to `/chat`.
2. The agent sends the conversation plus tool schemas to the configured LLM.
3. The model requests an allowlisted tool with JSON arguments.
4. Arguments are validated against a Pydantic schema; the tool queries SQLite.
5. The result (or a typed error) goes back to the model.
6. The model writes the explanation; the API also returns the structured tool results and
   provenance, and appends a fixed "scheduled data only" caveat.
7. The UI renders the reply, a complete data table when the prose omits rows, and a source
   panel.

Tool calls never touch the network, arbitrary URLs or SQL supplied by the model.

---

## 2. Prerequisites and installation

- Python **3.11+**
- [uv](https://docs.astral.sh/uv/) (recommended) — or plain `pip`
- Optional: [Ollama](https://ollama.com/) with a tool-capable model
- ~200 MB disk for the imported timetable

```bash
cd ai-agents
uv sync
```

Without `uv`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest pytest-asyncio   # for tests
```

---

## 3. Import a timetable

### 3.1 Demo fixture (no download, clearly fictional)

Useful for UI work and tests. These are **fictional** trains and stations.

```bash
uv run python -m scripts.import_timetable \
  --csv data/fixtures/demo_timetable.csv \
  --db data/demo.db \
  --source "FICTIONAL fixture data" \
  --licence "Test fixture - not real railway data" \
  --dataset-date 2026-01-01 \
  --note "Fictional data for development and tests. Not real trains."

LLM_PROVIDER=none RAILWAY_DB_PATH=data/demo.db uv run uvicorn app.api:app --port 8000
```

Open <http://localhost:8000>. `LLM_PROVIDER=none` uses a deterministic intent router, so no
model is required.

### 3.2 The real (but stale) 2017 timetable

Source: the Indian Railways time-table catalogue on
[data.gov.in](https://www.data.gov.in/catalog/indian-railways-train-time-table), published
under the Government Open Data License – India (GODL). The file used here is a mirrored copy
of that export (`Train_details_22122017.csv`, published 22 Dec 2017).

```bash
mkdir -p data/raw
curl -L -o data/raw/Train_details_22122017.csv \
  https://raw.githubusercontent.com/itzmeanjan/indian-railway/master/data/Train_details_22122017.csv

uv run python -m scripts.import_timetable \
  --csv data/raw/Train_details_22122017.csv \
  --db data/railways.db
```

Verified result on 2026-10-27:

```
Imported 11,112 trains, 8,148 stations, 186,119 stops into data/railways.db
Skipped 5 malformed or single-stop rows.
```

The import takes ~1.5 s and writes atomically (a failed import leaves the previous database
untouched). `data/` is git-ignored; the CSV and the `.db` are not committed.

CSV columns expected:

```
Train No, Train Name, SEQ, Station Code, Station Name, Arrival time, Departure Time,
Distance, Source Station, Source Station Name, Destination Station, Destination Station Name
```

Use `--source`, `--source-url`, `--licence`, `--dataset-date` and `--note` to record accurate
provenance for a different export.

**This dataset is old.** Train numbers, routes and timings have changed since 2017, and it
contains **no running-day column**. The app therefore never claims a train runs on a given
date or that the data is current. For a production system, replace the importer input with a
recent licensed export, or implement a live provider (section 7).

---

## 4. Install and run Ollama

```bash
# macOS
brew install ollama
ollama serve          # leave running in its own terminal
```

Pull a model that supports tool calling. Tested during development with `qwen2.5:3b`;
`llama3.1`, `qwen3:8b` and `mistral-nemo` are other common choices.

```bash
ollama pull qwen2.5:3b
ollama list
```

Small models sometimes paraphrase or abbreviate tables. The UI compensates by rendering the
exact tool rows when the prose omits any, and the API always returns structured
`tool_results`. Prefer a larger model for better prose.

---

## 5. Configure the LLM

```bash
cp .env.example .env
```

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
```

`OLLAMA_MODEL` must match an installed model exactly (`ollama list`). There is no hardcoded
default, so a missing value produces a clear 503 instead of a mysterious failure.

Start the app:

```bash
uv run uvicorn app.api:app --port 8000 --reload
```

Check configuration:

```bash
curl -s localhost:8000/health | python3 -m json.tool
```

`GET /health` reports the dataset row counts, dataset date, LLM provider/model, and
`status: ok|degraded`. A missing model, unreachable Ollama or missing database all show up
there.

### Configuration reference

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama`, `openai` or `none` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server |
| `OLLAMA_MODEL` | *(required for ollama)* | Installed tool-capable model |
| `OPENAI_BASE_URL` | — | OpenAI-compatible base URL (include `/v1`) |
| `OPENAI_API_KEY` | — | Optional for local endpoints |
| `OPENAI_MODEL` | — | Model name at that endpoint |
| `LLM_TIMEOUT_SECONDS` | `60` | Per-request timeout |
| `LLM_TEMPERATURE` | `0.1` | Sampling temperature |
| `AGENT_MAX_TOOL_ROUNDS` | `6` | Tool-call loop limit |
| `RAILWAY_DB_PATH` | `data/railways.db` | Imported SQLite file |
| `MAX_MESSAGE_CHARS` | `2000` | Request-size limit |
| `MAX_SESSIONS` | `500` | In-memory session cap |

Secrets belong in `.env` only. `.env` is git-ignored; `.env.example` contains placeholders.

---

## 6. Use it

Open <http://localhost:8000> and try:

- `Trains from Bhubaneswar to New Delhi on 15 November 2026`
- `Show the complete schedule for train 12801`
- `Which stations does it stop at?` (follow-up)
- `Compare 12801 and 12802 from Bhubaneswar to New Delhi on 2026-11-15`
- `Is 12801 running late today?` → explains that live status is not configured

### API

```bash
curl -s -X POST localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "Schedule of train 12801"}'
```

```json
{
  "session_id": "s_1caba1233cd54942",
  "reply": "…markdown answer…",
  "tool_results": [{"ok": true, "tool": "get_train_schedule", "data": {"…": "…"}, "provenance": {"…": "…"}}],
  "sources": [{"source": "…", "kind": "scheduled", "dataset_date": "2017-12-22"}],
  "degraded": false
}
```

- Omit `session_id` on the first request; reuse the returned id for follow-ups.
- `degraded: true` means a tool failed or a requested capability is unsupported.
- `tool_results` is the exact, typed data behind the prose — useful for client apps.

---

## 7. Using a real authorised railway data source

The current provider is `LocalTimetableProvider` (offline SQLite). Nothing scrapes IRCTC,
NTES or any website, and no public IRCTC API is assumed to exist.

To add a licensed source:

1. Implement `app.providers.base.RailwayProvider` (see `app/providers/local.py` for the
   contract). For live status and fares, implement `get_live_status` and
   `get_fare_and_availability`; otherwise leave them raising `FeatureUnsupported`.
2. Export it as a provider class and pass it to the app factory:

   ```python
   from app.api import create_app
   from app.providers.local import LocalTimetableProvider

   app = create_app(provider=MyLicensedProvider(...))
   ```

   or swap the provider construction in `app/api.py`.
3. Keep provider-specific HTTP, auth, retries, caching and rate limits inside the provider.
   Validate every upstream response before it reaches a tool.
4. Record provenance (`source`, `dataset_date`, `retrieved_at`, `kind`) so the UI can label
   live data as live.

Static timetable data can also be updated by re-running the importer with a newer CSV — the
schema is deliberately generic enough for any export with the same columns.

**Licensing note:** the data.gov.in catalogue is published under GODL-India. Check the terms
before redistributing the dataset, and never present imported data as official or live
unless your source contract allows it.

---

## 8. What works and what does not

| Capability | Status |
|---|---|
| Direct train search by route | ✅ works on imported data |
| Full schedule / route / halt times | ✅ |
| Train comparison | ✅ |
| Follow-up questions in a session | ✅ |
| Ambiguous station clarification | ✅ (typed error lists candidates) |
| Running days | ❌ not in the dataset — always reported unavailable |
| Live running status | ❌ unsupported unless a live provider is added |
| Fares / seat availability | ❌ unsupported without reservation-data access |
| PNR, booking, cancellation, login | ❌ out of scope |
| Multi-leg / connecting journeys | ❌ out of scope |
| Walking/auto between nearby stations | ❌ out of scope |

Data limitations are also enforced in code: every successful response carries a
deterministic caveat stating that the data is scheduled, the dataset date, and that
running-day information is absent — even if the model forgets to mention it.

---

## 9. Switching to an OpenAI-compatible endpoint

No agent, tool or UI code changes are needed:

```env
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1-mini
```

Works with any endpoint that implements `POST /chat/completions` and OpenAI-style
`tools`/`tool_calls` (OpenAI, vLLM, LM Studio, OpenRouter, etc.).

Caveats:

- Tool-calling support varies by model. If a model ignores tools, it will answer without
  data; the app still refuses to invent railway facts, but the answer may be unhelpful.
  Use a tool-capable model, or run with `LLM_PROVIDER=none`.
- Some providers require `tool_choice` adjustments; keep provider-specific quirks inside
  `app/llm/openai_compat.py`.
- If the endpoint is unreachable or rejects the key, `/chat` returns a safe error message
  rather than a stack trace.

---

## 10. Tests and troubleshooting

```bash
uv run pytest -q
```

Verified: **67 passed** on 2026-10-27 (Python 3.12). Tests use only fictional fixture data
and mocked providers — no internet or real railway API.

Coverage includes: station matching and ambiguity, train search (including overnight and
intermediate-stop durations), schedules and day rollovers, comparison ordering, missing
parameters, invalid dates and train numbers, unknown/extra tool arguments, tool allowlisting,
typed unsupported live/fare responses, provider failures, importer validation, LLM provider
configuration, Ollama/OpenAI message conversion, agent loops and max rounds, session context,
and API schemas/errors.

Manual smoke test performed: imported the 2017 dataset, ran the server with
`LLM_PROVIDER=none` and with Ollama `qwen2.5:3b`, and exercised search, full schedule and a
follow-up question.

| Symptom | Cause / fix |
|---|---|
| `503` mentioning `OLLAMA_MODEL` | Set `OLLAMA_MODEL` in `.env` to an installed model |
| "Could not connect to Ollama" | Run `ollama serve`, check `OLLAMA_BASE_URL` |
| Model answers without `tool_results` | Model did not call tools; use a tool-capable model, or `LLM_PROVIDER=none` |
| `dataset.status = missing` in `/health` | Run the importer; check `RAILWAY_DB_PATH` |
| "No station found for …" | Use the station code (`NDLS`) or a fuller name |
| "matches more than one station" | Choose one of the returned codes |
| `ImportError: app…` | Run commands from the repository root with `uv run` |
| `No module named scripts` | Use `python -m scripts.import_timetable`, not a direct file path |
| pytest warning about `httpx2` | Harmless Starlette deprecation warning |
| Wrong/old train numbers | Expected: dataset is from 2017 |

---

## Project layout

```
app/
  api.py              FastAPI app, /chat, /health, static serving
  agent.py            LLM tool loop + deterministic fallback router
  config.py           .env settings
  db.py               SQLite schema/helpers
  formatting.py       Markdown tables for the no-LLM router
  models.py           Pydantic schemas (station, stop, results, provenance)
  router_utils.py     Date/route parsing for the no-LLM router
  sessions.py         In-memory conversation store
  llm/                base.py, ollama.py, openai_compat.py
  providers/          base.py (interface), local.py (SQLite)
  tools/              railway.py (allowlist + schemas + execution)
  static/             index.html, app.js, styles.css
scripts/
  import_timetable.py Offline CSV → SQLite importer
data/
  fixtures/           Clearly fictional test data
  raw/                Downloaded CSVs (git-ignored)
tests/                pytest suite (67 tests)
```

### Security notes

- Tool names and arguments are validated against a closed allowlist and Pydantic schemas.
- The model cannot run code, supply SQL, fetch URLs or read files.
- Error messages are sanitised; stack traces stay in server logs.
- Secrets live only in environment variables; `.env` is git-ignored.
- Sessions are in memory and cleared on restart; there is no authentication. Add auth,
  rate limiting and a shared session store before exposing this publicly.
- The UI escapes all model output before rendering and sends a restrictive CSP.
