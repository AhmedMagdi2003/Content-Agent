# Make.com delivery through ngrok

The content app generates and reviews drafts using your existing LLM and Supabase
configuration. Make fetches approved jobs on its scenario schedule, claims one job
immediately before posting, then sends its result back. The app only records
`published` after receiving the platform's actual post ID and URL. Gmail review
drafts finish as `drafted`, without a publication timestamp or an email send.

This is a scheduled HTTP integration, not an incoming Make webhook. No Make
webhook URL is required. Schedule frequency depends on your Make plan. Use **Run
once** during initial testing. The Make scenario and platform account connections
must be configured in your Make account; preparing these files does not create them.

## 1. Fill in your public URL

If `.env.make` already exists, keep it: it contains your generated integration token.
Otherwise copy `.env.make.example` to `.env.make` and replace its token placeholder
with a distinct random secret (at least 32 characters). Generate one locally with:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(36))"
```

Keep database and provider keys in `.env`. The app loads `.env.make` afterward as
an override. Environment variables set by your shell take precedence over both files.
Your reviewer token signs you into the app; the separate `MAKE_API_TOKEN` gives
Make access only to its delivery queue and callbacks. Never put the reviewer token
in the Make scenario or commit `.env.make`.

Start ngrok in one PowerShell window:

```powershell
cd D:\ImpactCircles\Content-Agent
.\scripts\start_ngrok.ps1
```

Copy the assigned HTTPS origin, e.g. `https://your-assigned-domain.ngrok-free.app`,
into `PUBLIC_BASE_URL` in `.env.make`. Use your actual assigned URL; omit paths and
the trailing slash. The ngrok agent must already be installed and authenticated.

Start the app in another PowerShell window:

```powershell
cd D:\ImpactCircles\Content-Agent
.\scripts\start_content.ps1
```

Open **your ngrok URL**, sign in with the reviewer token, and keep both windows
running. Secure cookies are enabled for this HTTPS setup, so use the public URL
for the dashboard rather than the local HTTP address. The local test publisher on
8011 is not needed when `PUBLISHER_BACKEND=make`.

For an assigned persistent ngrok domain you can also start the tunnel explicitly:

```powershell
.\scripts\start_ngrok.ps1 -PublicUrl https://YOUR-ASSIGNED-DOMAIN.ngrok-free.app
```

Ngrok exposes the app running on your computer; it does not move the Python process
onto a hosted server. Sleeping, shutting down, or stopping the app/tunnel prevents
Make from connecting. If the domain changes, update `.env.make`, restart the app,
and update the first HTTP module in Make. The remaining job URLs are returned by
the app using `PUBLIC_BASE_URL`.

## 2. Check the environment

```powershell
.\.venv\Scripts\python.exe -m scripts.check_readiness --database --public
```

This validates configuration, checks the Supabase schema without changing it,
and checks the Make endpoint through ngrok. It prints no credentials.

To make one paid LLM call using fictional content and an in-memory test database:

```powershell
.\.venv\Scripts\python.exe -m scripts.check_readiness --live
```

The live probe allows one model call with an app budget of at most USD 0.01 using
the configured rates; it does not publish or store drafts in your cloud database.
Rates must match your provider/model for that estimate to be meaningful. The
prepared overlay uses verified standard GPT-4o-mini rates of USD 0.15 input / USD
0.60 output per million tokens, checked on 2026-10-23. Adjust the overlay if you
change the model. A successful probe is a connectivity/structure check, not a full
editorial evaluation or production certification.

## 3. Build the Make scenario

All HTTP requests **to this app** need these headers:

| Header | Value |
|---|---|
| `Authorization` | `Bearer ` followed by `MAKE_API_TOKEN` from `.env.make` |
| `ngrok-skip-browser-warning` | `true` |
| `Content-Type` | `application/json` for POST requests |

Store the bearer token in Make's credential storage where available. Otherwise,
treat the scenario as secret and remove credentials from any export you share.
The app's OpenAPI documentation at your public `/docs` URL describes the request
schemas. The separate `scripts/make/delivery_requests.http` file contains request
examples with placeholders. A credential-free reusable blueprint is available at
`scripts/make/content_delivery.blueprint.json`, derived from the tested workflow.
Import it into a **new inactive** scenario, set its polling URL, select the scoped
app HTTP connection in modules 1/3/5/8/9/10/12, select LinkedIn/Gmail connections,
and replace `reviewer@example.com` with the reviewer address. All connection IDs
and personal addresses were removed. The portable export itself has not been
re-imported and tested in a different account. Do not enable a duplicate scenario
alongside the existing one unless you intend to run multiple queue consumers.

| Step | Make module/action | Configuration |
|---|---|---|
| 1 | HTTP: Make a request | GET `PUBLIC_BASE_URL/api/v1/integrations/make/jobs?limit=20`. Parse the JSON response. |
| 2 | Iterator | Iterate over step 1's `jobs` array. An empty array means there is nothing approved to post. |
| 3 | Router | Filter the iterated `channel` into LinkedIn, newsletter, or an explicitly enabled website branch. |
| 4 | HTTP: Make a request in each branch | POST to the iterated `claim_url`. JSON body: `digest` mapped from that job. Parse the response. |
| 5 | Platform action | Connect the authorized account and post exactly step 3's `text`. |
| 6 | JSON: Create JSON | Build the successful result object described below using the actual platform response. |
| 7 | HTTP: Make a request | POST that JSON to the iterated `result_url`, with the app authentication headers. |

Use structured JSON fields / Make's JSON builder when mapping values, or
`escapeJSON` for string values; do not concatenate raw draft text. Platform actions must receive the **claim
response** text, not the older source brief or another editable draft.

Enable sequential scenario processing during initial setup. A failed claim
(`409`) means the job was already claimed, cancelled, or its approval changed:
stop that bundle before the platform module. Treat all non-2xx claim responses as
errors; never configure the scenario to continue to posting after one.

For LinkedIn, add a **Create a User Text Post** or **Create a Company Text Post**
module, create its connection, and authorize the account. Your account must have
the permissions required for the destination. Connect the website CMS in its
router branch. The app never receives your LinkedIn password or CMS credentials.

Default `MAKE_CHANNELS=linkedin,website` selects those two channels for new content;
all three drafts are still generated. The prepared local `.env.make` instead uses
`MAKE_CHANNELS=linkedin,newsletter`. The Make newsletter branch uses **Gmail:
Create a draft email**, never Send. Its recipient is the connected account itself,
subject is `Newsletter draft for review`, and body is escaped HTML containing the
exact claimed newsletter. Change the recipient in Make before using real audiences;
no mailing list or bulk-email sending is configured.

### Website template (intentionally disabled)

The third route is labeled **WEBSITE DISABLED — configure CMS first**. Its filter
requires `channel = website` AND the deliberately false `DISABLED = ENABLED`.
The app also excludes website from `MAKE_CHANNELS`, so there are two independent
guards. No website was created or connected.

The placeholder request at `https://configure-your-cms.example.invalid/api/posts`
is a generic adapter contract, **not a plug-and-play WordPress or other CMS API**.
Replace it with a native CMS module (WordPress, Webflow, etc.) or an authenticated
adapter implementing this contract:

```json
{"external_key":"CLAIM_IDEMPOTENCY_KEY","channel":"website","text":"EXACT_CLAIMED_ARTICLE"}
```

Send `Idempotency-Key` from the claim response. The adapter must persistently
deduplicate this key and return JSON with the actual `external_id` and public
`url` only after publication. Map these into the result callback. Configure its
own scoped credentials in Make; never reuse the app token for the CMS. Test with
a staging site first. Only then remove the false filter condition and add
`website` to `MAKE_CHANNELS`, restarting the app. Until these steps are completed,
website publication is a template, not a verified integration.

## 4. Report the actual result

Send this object only after the platform confirms success:

```json
{
  "digest": "DIGEST_FROM_CLAIM_RESPONSE",
  "attempt": 1,
  "status": "published",
  "external_id": "ACTUAL_PLATFORM_POST_ID",
  "url": "https://ACTUAL_PLATFORM_PUBLICATION_URL"
}
```

Map `attempt` from the claim response as a number; do not hardcode it. Map the
digest from the claim response. The URL and external ID must come from the actual
platform response or a verified lookup, never an invented test URL. Website and
LinkedIn success require a URL. Newsletter success requires an actual external ID
but may omit a URL if that provider has no permalink. Email provider acceptance
does not prove delivery to each recipient.

For **Gmail Create a draft email**, map its **Draft ID**, not its Message ID, and
report this instead (no `url` is required):

```json
{
  "digest": "DIGEST_FROM_CLAIM_RESPONSE",
  "attempt": 1,
  "status": "drafted",
  "external_id": "ACTUAL_GMAIL_DRAFT_ID"
}
```

Only newsletter jobs can finish as `drafted`. It is terminal and idempotent:
re-approving or retrying does not create another draft. It never means sent.

For automated failure reporting, create an error handler on each platform module. If the platform definitively
rejected the write and no post was created, send a sanitized result such as:

```json
{
  "digest": "DIGEST_FROM_CLAIM_RESPONSE",
  "attempt": 1,
  "status": "failed",
  "error_code": "PLATFORM_401"
}
```

If a timeout/lost response means a post **may have been created**, send:

```json
{
  "digest": "DIGEST_FROM_CLAIM_RESPONSE",
  "attempt": 1,
  "status": "uncertain",
  "error_code": "PLATFORM_TIMEOUT"
}
```

Use **JSON: Create JSON** to build these error bodies too. Do not forward raw
provider errors, passwords, or tokens. Do not automatically retry the posting
module after a timeout. If only the final callback fails, retry the same callback,
not the platform write. Repeating the same confirmed result is safe.

An `uncertain` job needs inspection in the destination account. Once you know the
outcome, report `published` with its real ID/URL, or `failed` only when you have
confirmed that no post exists. If a scenario crashes after claim and before any
callback, the app keeps `publishing`; inspect Make's history and the destination,
then submit the result for that exact attempt. Jobs never automatically become
eligible again on a timer, because a completed remote write may have lost its reply.

**Retry failed channels** queues only confirmed failures, with at most three
claimed posting attempts. It does not repeat published, drafted, or uncertain jobs. Editing
or regenerating cancels jobs that are still queued. Editing is blocked while a
claimed job is `publishing`; after a confirmed write, edits cannot retract the post.
Complete outstanding Make jobs before switching back to the local publisher.

## 5. First end-to-end test

1. Run the readiness checks, then leave Make's scenario in **Run once** mode.
2. Generate three drafts, review factual claims and citations, edit if needed,
   and select only the platform branches you actually connected.
3. Click **Approve & Publish**. The app should show `queued` and no published URL.
4. Run Make. Check its claim, platform result, and callback. Refresh the app: it
   should show `published`, the actual ID/URL, and the publication timestamp.
5. Confirm the exact approved text appears in the destination account.

For Gmail, expect `drafted` with a real Draft ID, no publication timestamp, and
the newsletter in Gmail Drafts. Do not click Send during this review-only test.

The saved scenario runs sequentially and keeps incomplete-execution retries off.
It currently stops on HTTP/platform errors rather than automatically reporting
them: a claimed job may remain `publishing` until an operator reconciles it.
Inspect Make history and the destination, then send the matching confirmed result.
Do not restart a platform module merely to repair a callback.

Use an authorized test destination for fictional data. Before posting publicly,
use a real, reviewed brief and a destination you are authorized to publish to.
These files do not connect to Impact Circles' channels or publish anything by themselves.

## References and verification

- [Make LinkedIn connection and posting modules](https://apps.make.com/linkedin)
- [Make webhook acceptance versus execution](https://help.make.com/webhooks)
- [ngrok CLI and HTTP forwarding](https://ngrok.com/docs/gateway/agent/cli)
- [Official GPT-4o-mini settings and pricing](https://developers.openai.com/api/docs/models/gpt-4o-mini)
- [Make Gmail modules, including Create a draft email](https://apps.make.com/gmail-modules)
- [Make HTML and JSON escaping functions](https://help.make.com/text-and-binary-functions)

Locally verified: live OpenAI draft generation and a read-only Supabase connection
with the six content tables. The Make scenario and scoped HTTP credential are
saved; LinkedIn and Gmail connections are visible in Make. A Make run successfully
fetched the queue through ngrok, claimed both exact human-approved revisions,
published the LinkedIn test, created the Gmail review draft, and reported both
results. The text was verified in LinkedIn and the connected Gmail Drafts UI.
After separate explicit user approval, the scenario was activated every 15 minutes.
Evidence: `sample_outputs/make-live-delivery-2026-10-23.json`. Website remains disabled.
