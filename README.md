# Content Agent

The existing Content Generation & Publishing Agent, extracted from the combined
workspace. It creates LinkedIn, newsletter and website drafts, retains revisions,
supports edits/rejection, and publishes the exact approved revision to selected
**local test** destinations. Finance is neither imported nor required to run.

## Run independently

From the repository:

```powershell
cd content-agent
uv sync --locked
uv run python -m scripts.demo_setup
uv run uvicorn content_app.main:app --host 127.0.0.1 --port 8001
```

In another terminal, also inside `content-agent/`:

```powershell
uv run uvicorn content_app.publisher:app --host 127.0.0.1 --port 8011
```

Open [Content Agent](http://127.0.0.1:8001). Copy `CONTENT_REVIEWER_TOKEN` from this
application's local `.env` to the sign-in form. No credentials are printed by setup.
The default demo uses the **existing source-preserving templates**, not live AI.
It still performs real HTTP publishing to the separate mock CMS/social server.
No real LinkedIn, email or Impact Circles account is connected. Newsletter publishing
is a local test page, not bulk email delivery.

Paste `tests/fixtures/project-update.txt`, generate drafts, compare against the
source, edit and **Save new revision**, select channels and save, then explicitly
click **Approve & Publish**. Open the saved publication URLs. Rejection stores a
reason. Edits or changed channel selection require approval of the new revision.
Retries retain successful channels and use the same idempotency key for each
revision/destination; a channel has at most three attempts.

## Separate configuration and data

Only `CONTENT_*` environment variables and `content-agent/.env` are consumed. Root
finance `.env` and unprefixed variables are not loaded. Local paths resolve relative
to this directory. Cookies use `content_session` instead of finance's `session`.

For Supabase set `CONTENT_MODE=cloud`, `CONTENT_DATABASE_URL` to a privileged
`postgresql+psycopg://...` connection, reviewer/session secrets and secure cookies.

```powershell
uv run python -m scripts.setup_db
```

Setup uses the independent `content_ops` PostgreSQL schema, enables RLS without
public policies, and requires no finance tables or original-file Storage bucket.
Use a separate Supabase project/role if stronger operational separation is needed.
SQLite demo data lives in `content-agent/data/content.db`; the mock publisher has
its own `content-agent/data/publisher.db`. These runtime files and secrets are ignored.
Cloud setup and PostgreSQL concurrency need credentials and are not claimed live.

## Preserve an existing combined-app local database

Stop the old combined app and publisher first. Run the new content demo setup,
then from `content-agent/`:

```powershell
uv run python -m scripts.import_legacy --source-sqlite ../data/workspace.db --publisher-sqlite ../data/publisher.db
```

The transfer opens the sources read-only. It preserves IDs, source text, drafts,
revision hashes, approvals/rejections, publications, content-specific audit events,
draft usage and test posts. It refuses conflicting destination records and is
idempotent when records match. Original finance records and legacy content tables
remain untouched. New content writes use only the independent database. The same
publisher port 8011 keeps historical local publication links usable after transfer.
This command migrates existing local SQLite data; a live Supabase data transfer
has not been tested. A separate Supabase schema is created by normal setup.

After both content servers are running, `uv run python -m scripts.smoke_demo`
executes the existing smoke sequence against port 8001 and saves actual outputs.

## Preserved model, publishing and telemetry behavior

The existing LangChain adapters for Gemini/OpenAI/xAI, versioned prompt, bounded
LangGraph draft flow, Pydantic schemas, grounding checks, approval hash, HTTP/HMAC
publisher, usage ledger, query timings and activity feed were reused. Domain
authorization and writes remain ordinary Python. Both graphs and model calls
disable ambient LangSmith export to avoid unintentionally exporting private input.

For a live model set `CONTENT_PROVIDER`, `CONTENT_MODEL_NAME`, matching prefixed key,
model-specific input/output token rates and pricing source/check date. The existing
cost guard requires known configured rates; missing usage remains unknown. A draft
call can make at most two attempts within the shared configured call/cost ceiling.
Live model calls were not verified without credentials.

`CONTENT_TRACING_BACKENDS=none` retains the internal Operations feed. The original
Langfuse/LangSmith exporters were not implemented/verified; other selections still
raise `TRACE_EXPORTER_NOT_VERIFIED`. Extraction does not replace this limitation
with a placeholder integration. Model costs remain estimates, not provider invoices.

## API and verification

Open [API docs](http://127.0.0.1:8001/docs). Use
`Authorization: Bearer <CONTENT_REVIEWER_TOKEN>` for integration clients. Browser
sessions require CSRF tokens. Existing routes are preserved:

- `POST /api/v1/content` generates and saves source/drafts together.
- `GET /api/v1/content/{id}` returns source, revisions and publication log.
- `PUT /api/v1/content/{id}` saves drafts/channel selection as a new revision.
- `POST .../{id}/reject`, `.../{id}/approve-and-publish`, `.../{id}/retry`.
- `GET /operations` shows sanitized internal activity and model usage/cost.

```sh
curl -H "Authorization: Bearer $CONTENT_REVIEWER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source":"The fictional River Research team reviewed its sampling checklist."}' \
  http://127.0.0.1:8001/api/v1/content
```

Zapier can call this authenticated JSON API over HTTPS when hosted. No live Zapier
configuration is claimed. Generation does not approve or publish anything.

```powershell
uv run ruff check .
uv run pytest -q
```

Tests are migrated from the original implementation and use isolated SQLite,
fake model responses and explicit fake transports. A separately named real loopback
HTTP test verifies network execution. Original combined-app outputs/screenshots in
`sample_outputs/legacy/` and `docs/legacy-screenshots/` are historical evidence,
not proof of running this extracted app. Refactor results and specification gaps
are recorded separately in `docs/` as they are verified.

The local publisher's contract supports idempotent retries. Ambiguous outcomes for
arbitrary production destinations have no reconciliation workflow. No new content
features or real platform adapters are being implemented during this extraction.
