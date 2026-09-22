# DemoCommerce Sandbox

A fake ecommerce company environment for testing the Ecommerce Order Support
Assistant, which lives in another repository. This is **not the AI product**.
It provides deterministic source data and realistic, independent HTTP failures.
The Product must use HTTP; it must not import this code or access this database.

One FastAPI service represents OMS, Logistics, Warehouse, and Support through
separate routers. SQLite persists seed records and accepted simulated replies.
No AI, UI, authentication, real providers, SaaS, or cross-system aggregation is included.
Implementation stops at the requested Sandbox S0-S1 scope.

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
history. It starts a new test run; prior-run keys can create new replies.
Seed timestamps are fixed relative to `2026-09-20T06:00:00Z`, not startup time.
For freshness tests the Product test clock should use this reference time.
Actual reply acceptance timestamps use current UTC.

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
uses real HTTP for health and S02/S04/S06/S08/S09/S12, and stops the process.
Tests cover scenario contents, timestamps, independent faults, missing records,
exact reply text, retry/conflict/new-key behavior, concurrent retries, restart,
and reset. No Product interpretation or expected AI answer is defined here.
