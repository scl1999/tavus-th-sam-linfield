# Tavus CVI take-home

A local Deloitte-style pair programming interview with Charlie, Tavus CVI/Daily, a React editor and draw.io, FastAPI and PostgreSQL. The assignment brief and captured Tavus documentation are under the gitignored `documentation/` directory. Slide and deck files are outside this repair.

## Local setup

Use Python 3.12+, Node 22.12+ and Docker. PostgreSQL and both application servers must bind to loopback. Copy `.env.example` into `.local_secrets/.env` and fill in your own credentials; preserve an existing file. The Docker Compose database requires `POSTGRES_PASSWORD` from the local environment. No database password is supplied by the application.

Create a Tavus API key in [Tavus PAL Maker](https://maker.tavus.io/), then add it to the local environment file. From the repository root:

```bash
mkdir -p .local_secrets
cp -n .env.example .local_secrets/.env
chmod 600 .local_secrets/.env
```

Open `.local_secrets/.env` in a text editor and set `TAVUS_API_KEY` to your key. Set `DATABASE_URL`, `CALLBACK_BASE_URL` and `CALLBACK_SECRET` for your local setup as described below. The file is ignored by Git; never put a real key in `.env.example` or commit it. Restart the backend after changing the key.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd frontend
npm ci
```

For a fresh database, apply `src/tavus_cvi/adapters/db/schema.sql`, import the retained `data/leetcode_first_100.json` through `PostgresRepository.upsert_problem`, then start the API. Existing installations receive additive, idempotent runtime migrations and recoverable workspace backfills at startup. No interviews, recordings or telemetry are deleted. Legacy interviews without an ownership token remain accessible to the trusted local operator through PostgreSQL; their UUID does not grant candidate access.

Pull the two digest-pinned official images listed in `config/execution.yaml` with `docker pull`. Docker must be available: execution fails closed without it. Run executes candidate-written test calls; it does not judge or grade solutions. Interview selection is restricted to Easy 1/20/26 and Medium 3/11/49. Both language starters are exercised in the container tests; Python typing imports and an empty method body are supplied without a solution.

## Callback delivery and starting services

Set `CALLBACK_BASE_URL` to the approved temporary HTTPS tunnel and generate a long random `CALLBACK_SECRET` in the local environment file. Tunnel **only** the separate gateway on `127.0.0.1:8001`; never tunnel port 8000, Vite or PostgreSQL.

```bash
PYTHONPATH=src .venv/bin/uvicorn tavus_cvi.api.callback_gateway:app --host 127.0.0.1 --port 8001
# In separate terminals, with the temporary tunnel running to port 8001:
PYTHONPATH=src .venv/bin/uvicorn tavus_cvi.api.app:app --host 127.0.0.1 --port 8000
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173`. Check `/api/readiness` before starting. Startup provisions the next immutable Charlie model card and binds its versioned tools to HMAC callbacks. Changing the tunnel URL or secret requires restarting/rebinding delivery before another call can start. Keep the gateway and tunnel running throughout the interview. Candidate APIs require an opaque HttpOnly, SameSite=Strict ownership cookie; mutations also check Origin and a CSRF request header. No registration screen is needed. The cookie uses `Secure` when `COOKIE_SECURE=true`; the default is local HTTP only.

Charlie's task video appears while he speaks; introductions use the full stage with candidate self-view. Questions and the editor have independent panes. Hints and rubrics stay server-side, and only opened statements reach the browser. Browser messages carry small public workspace notices under 4 KB. Charlie consults saved work and request-only hint reference through the authenticated context tool. Quiet updates do not request speech or guarantee an inference on every pause.

## Recovery, timing and recording

Refresh restores the owned interview, code, language, board and acknowledged revisions. Resume requires a user media gesture and rejoins the same room. Unacknowledged edits remain in a local backup. Revision conflicts, offline work and cutoff failures are surfaced; a local copy is not a saved server submission. Explicit phase tools allow a bounded 2.5-second checkpoint opportunity before changing stages. An unavailable browser cannot prevent a requested skip.

The server starts the clock once after successful media readiness. Setup has at most five minutes. Latest assessment boundaries are 05:00 introduction, 15:00 easy, 25:00 medium, 55:00 technical lock and 60:00 completion. Requested revisits preserve the clock and may continue until 55:00. A background worker enforces deadlines without browser polling. Local termination and cleanup intent commit before remote termination; pending cleanup retries after restart. The normal Tavus room cap is 65 minutes including setup. Refresh and reconnection do not pause or reset time.

Recording is explicitly **shared-screen video only**, with no captured microphone, camera or mixed call audio. Each MediaRecorder session gets a separate segment. Sequenced, checksummed chunks are idempotent; acknowledgements precede explicit finalization. IndexedDB retains a bounded 100 MiB retry queue; server chunks are limited to 10 MiB and segments to 1 GiB. Interrupted segments remain incomplete until a valid finalization arrives. Historical recording files remain untouched. Do not describe this as a complete call recording or a consent/retention product.

Code and boards remain on the interview linked to `candidates.id`, with existing candidate snapshots mirrored transactionally. These are latest accepted revisions, not a keystroke history. Complete browser-observed transcripts remain in PostgreSQL. Context uses deterministic phase-opening and recent-turn extracts, rebuilt from records after restart, with bounded paging of transcript/code/board. The assembled extract is capped at 5,000 locally counted tokens; this is not semantic summarization or a measurement of Tavus's entire prompt. Token telemetry is estimated, and unreported thinking tokens are NULL; historical values are preserved.

## Verification

```bash
.venv/bin/pytest -q
# To include PostgreSQL rollback integration checks, provide the local test URL:
TAVUS_TEST_DATABASE_URL="$DATABASE_URL" .venv/bin/pytest -q
.venv/bin/mypy src
.venv/bin/ruff check src tests
cd frontend
npm test
npm run build
npm run lint
```

Docker checks use real containers, including Python/TypeScript execution, host-file/secret/network isolation, read-only root, memory/process/output limits, timeout and cancellation cleanup. The existing UI fixture at `/tests/fixtures/workspace.html` is for layout review only. See `REPORT.md` for measured results and live-check limits. The trusted laptop operator can change configuration and inspect data; these repairs do not establish production certification, verified code ownership or calibrated assessment quality.

## Outage recovery

The client retries a failed join or an unexpected `left-meeting` event in the same room with increasing delays; leaving stops those retries. Initial session restoration, media-ready acknowledgements, code and the active whiteboard are retried after service or network recovery. Each unsaved revision remains in browser storage and can be downloaded as a local JSON backup. Server revision checks and the 55-minute cutoff still apply: work rejected after the cutoff stays local and is not represented as accepted.

Observed transcript events are placed in a bounded IndexedDB queue before upload, with stable event IDs and transactional server receipts. Retrying after a lost acknowledgement does not duplicate the stored event, and queued events observed before the interview ended may be delivered afterwards. Uploads retry while the app is open and on reconnection. A new interview waits for the old interview's queued uploads before replacing its ownership cookie. Candidate API requests have timeouts; room creation has a longer timeout and is not blindly retried because its outcome could be unknown.

Recovery depends on the room still existing, browser storage being available and the same ownership cookie being retained. Events that never reached the browser during a disconnection cannot be reconstructed by this queue. The clock continues through outages, and browser storage eviction or a device failure can still lose unacknowledged local data.

Charlie v9 retries a failed stage tool up to five times without asking the candidate to repeat the request. The callback gateway independently retries transient delivery failures up to five times using the same signed tool-call ID; validation and other permanent failures are returned immediately. If a failure happens before the request reaches the gateway, the additional attempts depend on Charlie following his instructions and Tavus accepting another tool invocation.

At the end, Charlie asks how the candidate felt it went and what they might improve, allows remaining questions, says goodbye, records completion with an authenticated tool, and then uses Tavus's built-in `end_call`. The existing 60-minute limit remains authoritative. If the completion marker remains unavailable after retries, Charlie is instructed to end the call anyway; its local outcome can then be recorded as a candidate departure instead of a completed interview.
