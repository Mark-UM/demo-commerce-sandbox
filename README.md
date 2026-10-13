# DemoCommerce Sandbox

A fake ecommerce company environment for testing the Ecommerce Order Support
Assistant, which lives in another repository. This is **not the AI product**.
It provides deterministic source data and realistic, independent HTTP failures.
The Product must use HTTP; it must not import this code or access this database.

One FastAPI service represents OMS, Logistics, Warehouse, Support and Policy through
separate routers. SQLite persists seed records and accepted simulated replies.
The complete environment includes deterministic ordinary data, golden scenarios,
service API Key authentication, HTTP fault controls, reply history, reset and
container deployment. No AI, UI, real providers, SaaS, or cross-system aggregation.

## Start independently

Requires Python 3.12+ and uv:

```sh
uv sync --locked
uv run uvicorn app.main:app --host 127.0.0.1 --port 9000
```

First startup seeds an empty database; later startups preserve replies.
Open http://127.0.0.1:9000/docs for the generated API schemas.
`SANDBOX_DB_PATH` optionally selects a SQLite file (default `./sandbox.sqlite3`).
Set this environment variable in your shell; `.env.example` is a reference and
is not loaded automatically. No other services or accounts are required.

All `/api/*` routes require `X-API-Key: demo-commerce-key` by default. Set
`SANDBOX_API_KEY` to select another key; an explicit empty value disables
authentication for isolated tests. Missing credentials return 401, wrong keys
403. Health, docs and OpenAPI remain public; Swagger's Authorize button supplies
the key. This service credential does not grant Product customer authorization.

Container startup (Docker Engine required):

```sh
docker compose up --build -d --wait
```

Compose binds localhost:9000 and persists SQLite in the `sandbox-data` volume.
The container uses Python 3.12, locked dependencies and a non-root process.
`docker compose restart` or `docker compose down` preserves data. HTTP reset
starts a new test run. `docker compose down -v` deletes the persistent volume.
Compose reads `.env` if present; the Python application reads shell environment.

Existing `s0-s1-v1` databases are preserved at startup. Explicit HTTP or CLI
reset upgrades them to the complete `sandbox-v2` seed and deletes old replies
and overrides. Before that reset, old datasets may lack the Policy record.

## API surface

| Method | Path | Source behavior |
|---|---|---|
| GET | `/health` | Database and seed health |
| GET | `/api/oms/orders/{order_id}` | Order and items |
| GET | `/api/oms/orders/{order_id}/parcels` | All OMS parcel references |
| GET | `/api/oms/customers/{customer_id}/orders` | Paginated customer orders |
| GET | `/api/logistics/shipments/{tracking_number}` | Source shipment status |
| GET | `/api/logistics/shipments/{tracking_number}/events` | Source tracking events |
| GET | `/api/warehouse/orders/{order_id}/notes` | Original free-text notes |
| GET | `/api/support/inquiries` | Discover inquiries with pagination/order filter |
| GET | `/api/support/inquiries/{inquiry_id}` | Customer inquiry |
| GET | `/api/support/inquiries/{inquiry_id}/replies` | Inspect accepted reply history |
| POST | `/api/support/inquiries/{inquiry_id}/replies` | Record simulated reply |
| GET | `/api/admin/scenarios` | List explicit fault overrides |
| PUT | `/api/admin/scenarios/{system}/{record_id}` | Set or replace a fault override |
| DELETE | `/api/admin/scenarios/{system}/{record_id}` | Restore golden behavior |
| POST | `/api/admin/reset` | Restore deterministic data and start a new test run |
| GET | `/api/admin/summary` | Stored record counts, seed version and reference time |
| GET | `/api/policy/order-support` | Static source policy facts |

Reply body: `{"text":"Your parcel is in transit.","idempotency_key":"reviewed-reply-1"}`.
Success is HTTP 200 with `reply_id`, `status: SENT`, and `sent_at`. SENT records
acceptance in this fake system; no real message is delivered. Reusing the same
inquiry/key and exact text returns the original receipt; different text gives 409.

Inquiry discovery returns an array ordered by inquiry ID. Use `limit` (1–100,
default 50), `offset` (nonnegative, default 0), and optional `order_id` for exact
matching; continue paging until an empty page. S12's inquiry remains discoverable
even though its order is absent. A filter with no matches returns `[]`.
Use `status=OPEN` for the pending queue and `status=REPLIED` for inquiries with
at least one accepted reply. Omitting status returns both. Status is exposed
on each inquiry; REPLIED means acceptance by this fake Support system, not
delivery, case resolution or Product approval. Filtering precedes pagination.
Retries do not duplicate queue transitions; reset restores OPEN inquiries.

Reply history accepts the same pagination parameters and returns an array in
acceptance order with `reply_id`, `inquiry_id`, exact `text`, `idempotency_key`,
`status` and `sent_at`. Retries do not add entries. An existing inquiry with no
replies returns `[]`; an unknown inquiry returns 404. These are source records,
not Product case states. Restart preserves history and reset removes it.

## Deterministic reset

For an HTTP-only test run, keep the service running and POST `/api/admin/reset`
with `{}` to restore the default seed, or
`{"base_time":"2026-10-13T06:00:00Z"}` to choose an explicit UTC reference.
The response is `{"status":"RESET","seed_version":"sandbox-v2","base_time":"..."}`.
Reset atomically replaces source data, clears replies/deduplication history and
fault overrides, and restores the golden S08/S09 failures. Invalid payloads
return 422 without changing data. A failed reset rolls back the whole transaction.
Finish all previous-run requests before reset; in-flight requests are not
cancelled. Reusing an old reply key afterward creates a reply in the new run.

The offline CLI remains available:

Stop the service, then run:

```sh
uv run python -m app.reset
```

Restart using the same database path. Reset restores identical source records,
retains the fixed S08/S09 fault behavior, and deletes all replies/deduplication
history and explicit fault overrides. It starts a new test run; prior-run keys
can create new replies.
Seed timestamps default to `2026-09-20T06:00:00Z`, not startup time.
For freshness tests the Product test clock should use the selected reference time.
Actual reply acceptance timestamps use current UTC.

For a later test or demonstration date, explicitly select a UTC reference time:

```sh
uv run python -m app.reset --base-time 2026-10-13T06:00:00Z
```

Use an ISO 8601 timestamp with `Z` or `+00:00`; timestamps without a timezone
or with a nonzero offset are rejected before reset. This shifts all known seed
timestamps by the same amount while preserving IDs, statuses, text, null updates,
and relative ages (normal shipment: T0 minus 10 minutes; S07: minus 72 hours).
No current clock is read to generate seed data. Repeating the same reference
time recreates identical source records. Restarts preserve the stored timestamps
and replies. A reset without `--base-time` restores the original default date,
even if the previous reset used another date. Reset still removes all replies.
The inquiry `created_at` exposes T0 over HTTP so test clients can inspect it.

## Scenarios and contracts

Exactly S01-S12 are defined: unshipped, in transit, delivered, two parcels,
waiting restock, planned shipment/uncollected, stale logistics, logistics 504,
warehouse 503, missing logistics, conflicting sources, and nonexistent order.
Golden scenarios contain 11 real orders and 12 inquiries; S12 references an
absent order. Ordinary IDs ORD-DEMO-101 through ORD-DEMO-209 add 109 orders.
The complete seed has 120 orders, 60 customer references, 20 SKUs, 143 parcels,
141 shipments, 539 tracking events, 120 warehouse notes and 60 inquiries.
All relations and quantities are deterministic; no random generator or clock
read is needed. ORD-DEMO-105 supplies instruction-like warehouse text as plain
source data; INQ-DEMO-106 supplies a refund inquiry. Neither triggers actions.
INQ-DEMO-107 has no order reference; ORD-DEMO-110 has a packed parcel without
carrier/tracking assignment; TRK-DEMO-113-1 has current status with empty event
history. These are successful source reads, distinct from S10's missing shipment.
See [scenario details](docs/scenarios.md) and [HTTP contract](docs/api-contract.md).
See [implementation and verification status](docs/implementation-status.md)
for completed scope, current limitations and the Product repository boundary.

The supplied root reference documents are copied unchanged into `docs/reference/`.
The supplied plan is named `03_ecommerce_environment_build_plan.md`, rather than
the `03_ecommerce_environment_plan.md` name mentioned in the request.
The current implementation retains the revised golden IDs and `/api` contracts
while fulfilling the broader Sandbox environment scope. Product adapters and
Product end-to-end validation remain in the separate Product repository.

## Verification

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run python scripts/smoke.py
```

Verify an already running local/container service (this sends a test reply):

```sh
uv run python scripts/verify_running.py --reset --receipt-file receipt.json
docker compose restart
uv run python scripts/verify_running.py --receipt-file receipt.json
```

Set SANDBOX_API_KEY in the verifier's environment to match the server.
`--reset` intentionally clears the previous test run; omit it to preserve data.
The receipt file checks that restart preserved the exact receipt and consumed
one-shot fault budget. The script leaves its simulated reply and override in
the environment for inspection. Reset clears them. GitHub Actions runs tests,
lint, HTTP checks, container build and restart verification on pushes/PRs.

The smoke script starts a separate Uvicorn process with a temporary SQLite file,
uses real HTTP for health and S02/S04/S06/S08/S09/S12, then verifies the inquiry,
order, parcel, shipment, warehouse and reply workflow, including discovery and
accepted reply lookup, with retry recovery and a
real client read timeout. It stops the process afterward.
It also resets the running service over HTTP, confirms cleared history and
restored faults, then submits and retries a reply in the new run.
Run `uv run python scripts/smoke.py --base-time 2026-10-13T06:00:00Z` to also
verify custom reset timestamps for normal and stale logistics over real HTTP.
Tests cover scenario contents, timestamps, independent faults, missing records,
exact reply text, retry/conflict/new-key behavior, concurrent retries, restart,
and reset. No Product interpretation or expected AI answer is defined here.

## Core fault controls

Use `system=logistics` with a tracking number or `system=warehouse` with an order
ID. Targets must already exist. Each rule affects only that source record;
logistics detail and events share the same rule and one-shot failure budget.

Example: PUT `/api/admin/scenarios/logistics/TRK-DEMO-004-1` with
`{"mode":"TIMEOUT_ONCE"}` makes the next logistics request for that parcel
return 504, then subsequent requests return the unchanged source data. The
second parcel, OMS, Warehouse, and Support remain independently available.

| Mode | Behavior |
|---|---|
| NORMAL | Return original source data, overriding default faults |
| TIMEOUT_ONCE | One request returns 504; subsequent requests succeed |
| ALWAYS_TIMEOUT | Each request immediately returns simulated upstream 504 |
| HTTP_500 | Each request returns 500 |
| HTTP_429 | Each request returns 429 with Retry-After: 1 |
| SLOW_RESPONSE | Delay each response by required delay_ms (1–10000), then return source data |
| STALE_DATA | Shift known source timestamps back 72 hours, preserving nulls |
| EMPTY_RESULT | Empty events/notes; shipment retains identity with null status/update |
| PARTIAL_FAILURE | This source record returns 503; other parcels remain independent |
| CONFLICTING_DATA | Warehouse says not handed over; logistics reports PICKED_UP |
| MALFORMED_RESPONSE | HTTP 200 with deliberately invalid JSON for adapter robustness tests |

For an actual client timeout, PUT `{"mode":"SLOW_RESPONSE","delay_ms":2000}`
and use a client timeout below two seconds. This differs from an immediate 504.
These controls do not retry requests or interpret any business status.

PUT replaces a rule and re-arms TIMEOUT_ONCE. Rules and consumed budgets persist
across restarts. DELETE is idempotent and restores the original golden behavior,
including S08's 504 and S09's 503. To make those scenarios succeed explicitly,
use NORMAL. GET lists only overrides, not the implicit golden defaults. Reset
clears all overrides. Controls are for local test use on the loopback service.
