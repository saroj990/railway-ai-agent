# Build an Indian Railways Train Information AI Agent

## Role

You are a senior software engineer and AI application architect. Build a **basic, reliable Indian Railways train-information AI agent**. Start with **Ollama** as the LLM provider, but design the code so that a future OpenAI-compatible LLM can be integrated by changing configuration rather than rewriting the application.

Work incrementally in the existing repository. First inspect the repository, identify its current stack and conventions, and then implement the smallest complete working version. Do not replace existing architecture without a clear reason.

## Product goal

Create a chat-based assistant that lets users ask questions in natural language about Indian Railways trains. The agent should use application tools and trusted data sources to retrieve facts, then explain the results clearly.

Example questions:
- “Find trains from Bhubaneswar to New Delhi on 15 November 2026.”
- “Show the complete schedule for train 12801.”
- “Which stations does this train stop at?”
- “What are the arrival and departure times at each station?”
- “Compare these trains by duration, departure time, and number of stops.”
- “Which days does this train run?”
- “Is this train running late today?” (only when a reliable live-status source is configured)

The first release focuses on train search, static schedules, route details, comparisons, and follow-up questions. Do not implement ticket booking, payments, PNR lookup, or account login unless explicitly requested later.

## Important data and reliability rules

1. **Do not invent railway facts.** Never fabricate train numbers, station codes, timings, stops, fares, availability, cancellations, or live running status.
2. Distinguish clearly between:
   - Scheduled timetable data
   - Live operational data
   - Reservation data such as fare and seat availability
3. A timetable does not prove that a train is running on a particular day or that seats are available.
4. If a required source is not configured or returns no data, explain that the information is unavailable. Do not fill gaps with model knowledge.
5. Show the source and, where available, the last-updated or retrieved time for results. Clearly label stale, partial, or unverified data.
6. Validate user input and API responses. Handle missing fields, timeouts, rate limits, malformed responses, and upstream errors gracefully.
7. Do not scrape IRCTC or other websites, bypass access controls, or assume a public API exists without first verifying permitted access and terms. Use documented, authorized APIs or imported datasets.
8. Do not claim to provide official or live information unless the configured source supports that claim.
9. Keep secrets in environment variables. Never commit API keys or credentials.

## Required architecture

Use a modular architecture with clear separation between the UI, agent, railway tools, data providers, and LLM provider.

Suggested components (adapt to the existing repository if needed):

- **Frontend:** A simple chat UI. If the repository has no frontend, choose a straightforward option appropriate for a small project.
- **Backend:** Python with FastAPI, unless the existing repository already uses a suitable framework.
- **Agent/service layer:** Interprets user intent, chooses permitted tools, validates tool arguments, and formats answers.
- **Railway tools:** Normal application functions that retrieve and normalize railway data. The LLM must not make up tool results.
- **Railway provider interface:** A common interface for timetable and live-data providers. Start with a local/imported dataset or a documented API that is actually available and authorized. If no reliable live API is configured, mark live status as unsupported.
- **Database:** Use SQLite for a minimal prototype unless the repository already has a database. Keep the data-access layer replaceable.
- **LLM provider interface:** Implement Ollama first. Add an OpenAI-compatible provider adapter later without changing agent logic or railway tools.

Keep provider-specific code isolated. Avoid scattering Ollama-specific request formats throughout the application.

## LLM provider abstraction

Create a small interface or adapter for the LLM provider. It should support the capabilities the agent actually needs, including structured responses and tool/function calling where the chosen model supports them.

Implement:
- `OllamaProvider` as the initial provider.
- `OpenAICompatibleProvider` as a future-ready adapter or a clearly documented extension point. Do not require OpenAI credentials to run the initial Ollama version.
- Configuration through environment variables, for example:

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=<your-installed-tool-capable-model>
OPENAI_BASE_URL=
OPENAI_API_KEY=
OPENAI_MODEL=
```

Use sensible defaults where possible. Do not hardcode a model name that may not be installed. Document how to set `OLLAMA_MODEL`.

Important: OpenAI-compatible APIs and models do not all support the same tool-calling behavior. Detect or document capability limitations. If the selected Ollama model cannot reliably call tools, use a constrained structured-output/intent-routing fallback or return a clear error; never silently invent railway data. Validate all model-generated tool names and arguments against an allowlist and schemas.

## Initial railway tools

Implement a minimal, testable tool layer with functions such as:

- `search_trains(from_station, to_station, journey_date)`
- `get_train_schedule(train_number)`
- `get_train_route(train_number)`
- `compare_trains(train_numbers, from_station, to_station, journey_date)`

Define optional extension points for:
- `get_live_status(train_number, journey_date)`
- `get_station_trains(station_code, date)`
- `get_fare_and_availability(train_number, from_station, to_station, journey_date, travel_class)`

Only expose live status, fares, or availability if a real configured provider supports them. Otherwise return a typed “not configured / unsupported” result.

Use station codes and canonical identifiers internally where possible. Support station-name lookup and ambiguous-name clarification. If origin, destination, or date is missing, ask the user for the missing information rather than guessing. Parse dates explicitly and use the `Asia/Kolkata` timezone for Indian railway dates and timestamps.

## Data layer

Create normalized models/schemas for at least:
- Station: code, name, optional aliases
- Train: number, name, running-day information where available
- Train stop: train number, station code, sequence, arrival time, departure time, halt duration, distance where available
- Data provenance: source name, retrieval/update timestamp, and whether the data is scheduled, live, or reservation data

Do not bundle invented sample records that look real. If demo data is needed for UI development or tests, label it prominently as fictional fixture data and never present it as live or official information.

If a railway dataset is not available in the repository, do not pretend the search is functional. Implement the provider interface, provide a small clearly labelled fixture for tests if useful, and document exactly how a real authorized dataset or API can be configured. Keep dataset import/update processes separate from request handling.

## Agent behavior

The agent should:
1. Understand the user's question and identify the required railway operation.
2. Ask for missing essential details (for example, travel date or which of two similarly named stations).
3. Call only the relevant allowlisted tool(s).
4. Validate tool arguments and results.
5. Answer using retrieved data, with clear tables or lists for schedules and comparisons.
6. Preserve relevant context for follow-up questions in the same conversation, such as “What about its stops?” after a train has been selected.
7. Explain uncertainty and data-source limitations.
8. Avoid exposing internal prompts, credentials, or implementation secrets.

For a full schedule, show available fields such as station sequence, station name/code, arrival, departure, halt duration, and distance. Represent unavailable values as “Not available,” not invented values. Explain that times are scheduled unless the source explicitly provides live estimates.

## API and UI requirements

Create a minimal chat interface and backend endpoint(s), for example:
- `POST /chat` for a user message and conversation/session identifier
- `GET /health` for health checks

Use typed request/response schemas. Return clear errors without leaking stack traces or secrets. The UI should display:
- User and assistant messages
- Train-search results in readable tables/cards
- Source and freshness information where available
- A clear indication when live status or reservation information is not configured
- Loading and error states

Keep the first UI simple and usable on desktop and mobile. Do not spend time on elaborate styling before core functionality and tests work.

## Security and operational requirements

- Read configuration from environment variables and provide a `.env.example` with placeholders only.
- Add `.env` and other secret files to `.gitignore`.
- Set reasonable request timeouts and handle provider failures.
- Add basic input validation, request-size limits, and safe error messages.
- Restrict the model to an allowlist of known tools; never execute arbitrary shell commands or model-generated code.
- Do not let the model directly query arbitrary URLs or SQL.
- Add logging that is useful for debugging but excludes secrets and unnecessary personal data.
- Include a disclaimer that the application is an independent information assistant and is not an official Indian Railways or IRCTC service unless formally authorized.

## Testing requirements

Add automated tests for:
- Station matching, including ambiguous station names
- Train search and schedule retrieval
- Missing required parameters
- Invalid dates and train numbers
- Empty and partial provider responses
- Provider timeout/error handling
- Unsupported live-status and reservation requests
- Tool allowlisting and schema validation
- LLM provider configuration and fallback behavior
- API endpoint response schemas

Use mocked railway providers in tests so tests do not depend on the internet or a real railway API. Clearly separate fixture data from real data.

## Documentation

Write a `README.md` that explains:
1. Architecture and data flow
2. Prerequisites and installation
3. How to install and run Ollama
4. How to pull/select a model suitable for tool calling or structured output
5. How to configure `OLLAMA_BASE_URL` and `OLLAMA_MODEL`
6. How to start the backend and frontend
7. How to configure a real authorized railway data source
8. Which capabilities work now and which remain unsupported
9. How to switch to an OpenAI-compatible endpoint later using configuration
10. How to run tests and troubleshoot common failures

Include exact commands appropriate to the repository and operating system where known. Do not claim a command was tested unless it was actually run.

## Implementation workflow

Follow this sequence:
1. Inspect the repository and summarize the existing structure before editing.
2. Propose a concise implementation plan based on the repository.
3. Implement a minimal vertical slice: one user question, one validated tool call, one railway provider, and one clear response.
4. Add the provider abstraction and environment-based Ollama configuration.
5. Add the API and minimal chat UI if absent.
6. Add tests and documentation.
7. Run available tests, linting, and type checks. Fix failures caused by the implementation.
8. Report exactly what works, what was tested, and what still requires a real railway data source.

Do not attempt to implement every possible railway feature at once. Prefer a small, working, testable system over a large scaffold.

## Definition of done

The first release is complete when:
- The project starts using documented commands.
- Ollama configuration is externalized and does not require an OpenAI API key.
- The LLM provider is isolated behind an interface so another OpenAI-compatible provider can be added later.
- At least one railway tool works against a clearly identified data source.
- The application never fabricates railway information when data is missing.
- Unsupported live status, fare, and availability features are clearly communicated.
- Tests cover the main tools and error paths.
- The README accurately describes setup, data limitations, and future provider integration.

Start by inspecting the repository, then implement the first working version. Ask questions only when a decision is genuinely blocking; otherwise choose simple defaults and document them.
