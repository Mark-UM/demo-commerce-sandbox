# DemoCommerce Sandbox

A fake ecommerce company environment for testing the Ecommerce Order Support
Assistant, which lives in another repository. This is **not the AI product**.
It provides deterministic source data and realistic, independent HTTP failures.
The Product must use HTTP; it must not import this code or access this database.

One FastAPI service represents OMS, Logistics, Warehouse, and Support through
separate routers. SQLite persists seed records and accepted simulated replies.
No AI, UI, authentication, real providers, SaaS, or cross-system aggregation is included.
S0-S1 is the baseline; the next core increment adds independent HTTP fault controls.

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

## API surface

| Method | Path | Source behavior |
|---|---|---|
| GET | `/health` | Database and seed health |
| GET | `/api/oms/orders/{order_id}` | Order and items |
| GET | `/api/oms/orders/{order_id}/parcels` | All OMS parcel references |
| GET | `/api/logistics/shipments/{tracking_number}` | Source shipment status |
| GET | `/api/logistics/shipments/{tracking_number}/events` | Source tracking events |
| GET | `/api/warehouse/orders/{order_id}/notes` | Original free-text notes |
| GET | `/api/support/inquiries/{inquiry_id}` | Customer inquiry |
| POST | `/api/support/inquiries/{inquiry_id}/replies` | Record simulated reply |
| GET | `/api/admin/scenarios` | List explicit fault overrides |
| PUT | `/api/admin/scenarios/{system}/{record_id}` | Set or replace a fault override |
| DELETE | `/api/admin/scenarios/{system}/{record_id}` | Restore golden behavior |

Reply body: `{"text":"Your parcel is in transit.","idempotency_key":"reviewed-reply-1"}`.
Success is HTTP 200 with `reply_id`, `status: SENT`, and `sent_at`. SENT records
acceptance in this fake system; no real message is delivered. Reusing the same
inquiry/key and exact text returns the original receipt; different text gives 409.

## Deterministic reset

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
There are 11 real orders and 12 inquiries; S12 references an absent order.
See [scenario details](docs/scenarios.md) and [HTTP contract](docs/api-contract.md).

The supplied root reference documents are copied unchanged into `docs/reference/`.
The supplied plan is named `03_ecommerce_environment_build_plan.md`, rather than
the `03_ecommerce_environment_plan.md` name mentioned in the request.
The current request overrides their broader future scope and older scenario IDs.

## Verification

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run python scripts/smoke.py
```

The smoke script starts a separate Uvicorn process with a temporary SQLite file,
uses real HTTP for health and S02/S04/S06/S08/S09/S12, then verifies the inquiry,
order, parcel, shipment, warehouse and reply workflow with retry recovery and a
real client read timeout. It stops the process afterward.
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

For an actual client timeout, PUT `{"mode":"SLOW_RESPONSE","delay_ms":2000}`
and use a client timeout below two seconds. This differs from an immediate 504.
These controls do not retry requests or interpret any business status.

PUT replaces a rule and re-arms TIMEOUT_ONCE. Rules and consumed budgets persist
across restarts. DELETE is idempotent and restores the original golden behavior,
including S08's 504 and S09's 503. To make those scenarios succeed explicitly,
use NORMAL. GET lists only overrides, not the implicit golden defaults. Reset
clears all overrides. Controls are for local test use on the loopback service.
