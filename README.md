# AI Content Generation & Automated Publishing Agent

An automated content operations workspace that transforms research updates, project announcements, and event notes into three tailored, fact-grounded communication drafts (LinkedIn, newsletter, and website), provides revision management, enforces strict human approval gates, and executes automated multi-channel publication via HTTP APIs.

---

## Features

- **Multi-Channel Drafting**: Transforms a single input source into three distinct drafts:
  - **LinkedIn**: Short, engaging, professional post with relevant hashtags.
  - **Newsletter**: Concise executive briefing and progress summary for stakeholders.
  - **Website**: Titled, structured article or announcement.
- **Factual Grounding**: Guardrails prevent the generation of unsourced statistics, citations, quotes, or claims.
- **Revision & Approval State Machine**:
  - Each edit creates an immutable snapshot with an incremented revision number and SHA-256 digest.
  - Publication is strictly blocked until an authorized reviewer clicks **Approve & Publish**.
  - Any edit or change in channel selection invalidates prior approvals, requiring re-approval.
  - Reviewer rejections are recorded with justification and block publication.
- **Automated Multi-Channel Publishing**:
  - Sends signed HTTP POST requests with HMAC SHA-256 authentication to test CMS and social endpoints.
  - Tracks per-channel status (`published`, `failed`, `uncertain`), external IDs, URLs, timestamps, and retry counts.
  - Records every publication attempt; timeout outcomes are reconciled by idempotency key before another POST is allowed.
  - Idempotent execution protects against duplicate posts on retry or concurrent requests.
- **Authoritative Persistence**: Backed by Supabase PostgreSQL in an isolated `content_ops` schema with Row Level Security (RLS).
- **Operations & Cost Ledger**: Sanitized timeline joining HTTP requests, model token counts, latency, and estimated provider costs.

---

## Quickstart

### Prerequisites
- Python 3.12 or 3.13
- [`uv`](https://docs.astral.sh/uv/) package manager

### 1. Install Dependencies
```powershell
uv sync --locked
```

### 2. Configure Environment
Copy `.env.example` to `.env` and fill in your configuration:
```powershell
Copy-Item .env.example .env
```

### 3. Initialize Database Schema
Run the database setup script to create the `content_ops` PostgreSQL schema and tables:
```powershell
uv run python -m scripts.setup_db
```

### 4. Start the Application & Test Publisher

You will run two local services:

**Terminal 1 — Content Agent Dashboard & API (Port 8001):**
```powershell
uv run uvicorn content_app.main:app --host 127.0.0.1 --port 8001
```

**Terminal 2 — Local Test Publisher Server (Port 8011):**
```powershell
uv run uvicorn content_app.publisher:app --host 127.0.0.1 --port 8011
```

Open [http://127.0.0.1:8001](http://127.0.0.1:8001) in your browser.  
Sign in using the `CONTENT_REVIEWER_TOKEN` configured in your `.env` file.

---

## Environment Variables Reference

All application settings are prefixed with `CONTENT_` and loaded from `.env`.

| Variable | Type | Allowed Values / Format | Default | Description |
|---|---|---|---|---|
| `CONTENT_MODE` | string | `cloud`, `demo` | `cloud` | Operational mode. Set to `cloud` for Supabase PostgreSQL. `demo` allows local offline SQLite storage. |
| `CONTENT_DATABASE_URL` | string | `postgresql+psycopg://...` or `sqlite://...` | *Required* | Authoritative database connection string. For Supabase, use the pooled PostgreSQL URL with `postgresql+psycopg://`. All tables live in `content_ops` schema. |
| `CONTENT_REVIEWER_TOKEN`| string | String (min 24 characters) | *Required* | Secret token used by reviewers to log into the web dashboard and for Bearer token API authorization. |
| `CONTENT_SESSION_SECRET`| string | String (min 24 characters) | *Required* | Secret key used to sign `content_session` HTTP cookies. |
| `CONTENT_SECURE_COOKIES`| boolean| `true`, `false` | `false` (local) / `true` (prod) | Whether to enforce `Secure` flag on session cookies (set `true` when hosted behind HTTPS). |
| `CONTENT_LOCAL_DATA_DIR`| path | Directory path | `data` | Local directory for storing local logs, test data, or local SQLite database. |
| `CONTENT_PROVIDER` | string | `none`, `gemini`, `openai`, `xai`, `fixture` | `none` | AI drafting provider. Choose `gemini` for Google GenAI, `openai` for OpenAI, `xai` for Grok, or `fixture` for template replay. |
| `CONTENT_MODEL_NAME` | string | Model identifier | e.g. `gemini-2.0-flash` | The specific model identifier to query (e.g. `gemini-2.0-flash`, `gpt-4o-mini`). |
| `CONTENT_GOOGLE_API_KEY`| string | API key string | Optional | Google Gemini API key (required if `CONTENT_PROVIDER=gemini`). |
| `CONTENT_OPENAI_API_KEY`| string | API key string | Optional | OpenAI API key (required if `CONTENT_PROVIDER=openai`). |
| `CONTENT_XAI_API_KEY` | string | API key string | Optional | xAI API key (required if `CONTENT_PROVIDER=xai`). |
| `CONTENT_PROVIDER_TIMEOUT`| integer| Seconds | `45` | Timeout in seconds for LLM provider API requests. |
| `CONTENT_MAX_LLM_CALLS` | integer| `1`, `2`, `3` | `3` | Maximum automated LLM attempts permitted per generation run. |
| `CONTENT_MAX_JOB_COST_USD`| decimal string | Numeric string (e.g. `0.10`) | `0.10` | Hard cost ceiling per drafting job. |
| `CONTENT_MAX_INPUT_TOKENS`| integer| Number of tokens | `32000` | Maximum input token limit permitted per drafting call. |
| `CONTENT_INPUT_USD_PER_MILLION` | decimal string | Rate in USD | e.g. `0.10` | Provider pricing rate per 1M input tokens for cost calculation. |
| `CONTENT_OUTPUT_USD_PER_MILLION`| decimal string | Rate in USD | e.g. `0.40` | Provider pricing rate per 1M output tokens for cost calculation. |
| `CONTENT_PRICING_SOURCE_URL` | string | URL string | e.g. `https://ai.google.dev/pricing` | Documented source URL for token pricing rates. |
| `CONTENT_PRICING_CHECKED_AT` | string | Date string (`YYYY-MM-DD`) | e.g. `2026-10-21` | Date when token pricing was checked. |
| `CONTENT_PUBLISHER_URL` | string | URL string | `http://127.0.0.1:8011` | Destination URL of the test publishing service. |
| `CONTENT_PUBLISHER_SECRET` | string | Secret string | *Required* | Shared HMAC SHA-256 secret key for signing outbound publication payloads. |
| `CONTENT_TRACING_BACKENDS` | string | `none`, `langfuse`, `langsmith`, `both` | `none` | External LLM observability export. Keep `none` to use internal database audit feed without cloud tracing. |

---

## API Endpoints

All endpoints under `/api/v1` require `Authorization: Bearer <CONTENT_REVIEWER_TOKEN>`.

- `POST /api/v1/content`: Submit a source update; triggers bounded LangGraph workflow to generate and save three channel drafts.
- `POST /api/v1/content/{id}/generate`: Regenerate three drafts for an existing item; requires the current revision number and creates a new revision.
- `GET /api/v1/content/{id}`: Retrieve source update, full revision history, current drafts, and publication logs.
- `PUT /api/v1/content/{id}`: Save edits to drafts and/or channel selections as a new immutable revision.
- `POST /api/v1/content/{id}/approve-and-publish`: Authorize publication of the current revision to selected channels. Triggers automated HTTP calls to publisher.
- `POST /api/v1/content/{id}/reject`: Reject the current draft with justification; blocks publishing until revised.
- `POST /api/v1/content/{id}/retry`: Safely retry publishing failed channels without republishing succeeded channels.
- `GET /api/v1/activity`: Retrieve correlated operational events and LLM cost ledger.
- `GET /health`: Health and service status endpoint.

---

## Testing & Quality

Run tests:
```powershell
uv run pytest -q
```

Run code formatting and linting:
```powershell
uv run ruff check .
```

## Free end-to-end demonstration

The bundled publisher is a local HTTP CMS/social test service. It is deliberately not LinkedIn or a production CMS: it accepts HMAC-authenticated requests, stores posts in SQLite, returns an external ID and a browsable URL, and supports idempotency and reconciliation. This is the assessment-safe demonstration when live platform permissions are unavailable.

For a no-account demo, use `scripts.demo_setup` to create a local SQLite database and secrets, then start both services in separate PowerShell windows:

```powershell
uv run python -m scripts.demo_setup
uv run uvicorn content_app.publisher:app --host 127.0.0.1 --port 8011
uv run uvicorn content_app.main:app --host 127.0.0.1 --port 8001
```

Submit through the authenticated API (copy the token from `.env`):

```powershell
$token = '<copy CONTENT_REVIEWER_TOKEN from .env>'
$h = @{ Authorization = "Bearer $token" }
$item = Invoke-RestMethod http://127.0.0.1:8001/api/v1/content -Method Post -Headers $h `
  -ContentType 'application/json' -Body (@{source='The fictional River Research team reviewed a sampling checklist at its workshop.'} | ConvertTo-Json)
$draft = Invoke-RestMethod "http://127.0.0.1:8001/api/v1/content/$($item.id)" -Headers $h
Invoke-RestMethod "http://127.0.0.1:8001/api/v1/content/$($item.id)/approve-and-publish" -Method Post -Headers $h `
  -ContentType 'application/json' -Body (@{revision=1; digest=$draft.revisions[0].digest} | ConvertTo-Json)
```

The response contains one publication per selected channel. Open each returned `url`, or browse `http://127.0.0.1:8011/`; `GET /api/v1/content/{id}` and `GET /api/v1/activity` show durable statuses and audit events. Editing, regenerating, rejecting, or changing selected channels invalidates the previous approval.

To connect production destinations later, implement the same `Publisher.publish` contract behind a new adapter. WordPress requires an application password and a reachable HTTPS site. LinkedIn requires an approved official application and the appropriate member or organization publishing permission; a free account alone does not guarantee that permission. Do not put those credentials in browser code or bypass platform restrictions.
