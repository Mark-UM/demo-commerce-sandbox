# DemoCommerce source HTTP contract

The Pydantic models in `app/schemas.py` and generated `/openapi.json` define the
concrete schema. These are raw source payloads, not canonical Product snapshots.
All object fields listed by the schema are required, including nullable fields.
Collections return bare arrays. Unknown records return 404; a known unfulfilled
order's parcel array can be empty. Shipment status is explicit and never inferred
from event ordering. Status strings remain open rather than a universal enum.

| Source response | Fields |
|---|---|
| Order | order_id, customer_reference (nullable), status, items, created_at, updated_at (nullable) |
| Item | sku, product_name, quantity (positive integer) |
| Parcel | parcel_id, order_id, carrier (nullable), tracking_number (nullable), updated_at (nullable) |
| Shipment | tracking_number, parcel_id, status (nullable), updated_at (nullable) |
| Event | event_id, parcel_id, status, description, occurred_at, updated_at (nullable) |
| Note | note_id, order_id, text, created_at, updated_at (nullable) |
| Inquiry | inquiry_id, order_id (nullable), customer_message, created_at |
| Reply receipt | reply_id, status (SENT), sent_at |
| Policy fact | code, content, updated_at (nullable); envelope has facts array |

Source identity comes from the subsystem URL: demo_oms, demo_logistics,
demo_warehouse, or demo_support. IDs identify records within those sources.
Product adapters map `order_id` to `external_order_id`, `updated_at` to
`source_updated_at`, and warehouse `text` to `note_text`. They assign their own
`fetched_at`. The Sandbox never supplies freshness or canonical snapshots.
Source timestamps use UTC ISO 8601 with Z; unknown timestamps are null.
Seed data never changes with wall-clock time. The reset CLI accepts an explicit
UTC `--base-time`; the default remains 2026-09-20T06:00:00Z. All known timestamps
shift together, nulls remain null, and restarts preserve the stored data.
See README for the reference clock and reset semantics.

POST reply takes `text` and `idempotency_key` in JSON, with inquiry ID in the path.
Blank values and unknown fields produce 422. Text is preserved exactly, including
surrounding whitespace. Limits are 10,000 text characters and 200 key characters.
Deduplication scope is `(inquiry_id, idempotency_key)` and survives restarts.
Same pair/text returns the original HTTP 200 receipt. Different text produces
409. A different key or inquiry creates a new simulated reply. SQLite serializes
the check and insertion atomically. Reset deletes this history.

Errors use `{"error":{"code":"...","message":"...","request_id":"..."}}`.
An optional `X-Request-Id` is echoed in the response header and error object;
otherwise the service generates one. Missing records are 404, validation is 422,
S08 logistics is 504, and S09 warehouse is 503. Failure injection is centralized
in `app/scenarios.py`. S08 is an immediate simulated upstream 504, not an
intentional client-side socket timeout.

## Core increment: independent fault controls

GET `/api/admin/scenarios` lists explicit overrides. PUT
`/api/admin/scenarios/{system}/{record_id}` accepts `mode` and optional
`delay_ms` (default 0). Supported systems are logistics (tracking number) and
warehouse (order ID); nonexistent targets return 404. Modes are NORMAL,
TIMEOUT_ONCE, ALWAYS_TIMEOUT, HTTP_500, HTTP_429, SLOW_RESPONSE, STALE_DATA,
EMPTY_RESULT, PARTIAL_FAILURE, CONFLICTING_DATA and MALFORMED_RESPONSE.
SLOW_RESPONSE requires delay_ms from 1 to 10000; other modes require 0.
Unknown fields, invalid systems/modes and invalid delays return 422.

PUT returns `system`, `record_id`, `mode`, `delay_ms`, `remaining_failures`.
Remaining failures is 1 then 0 for TIMEOUT_ONCE, otherwise null. One-shot
consumption is atomic and shared by a tracking number's detail and events
requests. Subsequent reads use unchanged source data, even for S08/S09.
HTTP_429 returns the structured RATE_LIMITED error and Retry-After: 1;
HTTP_500 uses SCENARIO_FORCED_FAILURE. Both timeout modes produce 504 with
the source's TEMPORARILY_UNAVAILABLE error. SLOW_RESPONSE lets the caller's
own timeout expire and does not hold a SQLite lock or block the async event loop.

Rules and consumed budgets persist across service restarts. PUT replaces a rule
and resets its budget. DELETE on the same path returns 204, including when no
override exists, and restores the golden default. NORMAL suppresses default
faults. Reset clears overrides. GET reports only explicit overrides. These
controls never aggregate sources or implement retries. STALE_DATA shifts each
known source timestamp back 72 hours, preserving nulls. EMPTY_RESULT returns
empty event/note lists or a shipment with null status/update and unchanged
identity. PARTIAL_FAILURE makes the targeted record unavailable with 503;
other parcels are queried independently, without 207 or a partial envelope.
CONFLICTING_DATA supplies warehouse text saying not handed to the carrier or
logistics status PICKED_UP. MALFORMED_RESPONSE intentionally bypasses schema
validation to send incomplete JSON with HTTP 200. These overrides affect only
the response; DELETE restores the stored source payload.

All `/api` routes require X-API-Key by default (demo-commerce-key); configure
SANDBOX_API_KEY to change it or explicitly empty to disable for isolated tests.
Missing key is 401/UNAUTHORIZED; wrong key is 403/FORBIDDEN. Authentication runs
before fault consumption or mutations. Health/docs/OpenAPI are public.
GET `/api/policy/order-support` returns two static facts, updated at T0 minus
five days. GET `/api/oms/customers/{customer_id}/orders` returns source orders
in ID order with limit/offset pagination; unknown customer is 404, offset past
the end is []. GET `/api/admin/summary` provides one consistent database snapshot
of record counts, customer/SKU counts, golden scenario count, seed version,
reference time, accepted replies and explicit fault overrides. It is inventory
metadata, not an order context. Unexpected internal errors use the same error
envelope with INTERNAL_ERROR and do not expose exception content.

## Resolved differences from reference documents

POST `/api/admin/reset` takes an explicit JSON object. `{}` or
`{"base_time":null}` selects the default T0; a `base_time` string selects an
ISO 8601 UTC reference (Z or +00:00). Naive/non-UTC timestamps, timestamps too
early for the five-day seed offset, numeric timestamps and unknown fields are
422. The response has `status: RESET`, `seed_version: sandbox-v2`, and the chosen
UTC `base_time`. Source records, reply/deduplication history, and fault overrides
are reset in one transaction; validation or transaction failure preserves the
previous run. The service remains running. Finish old requests before reset,
since the endpoint does not cancel in-flight work. Default S08/S09 failures
return afterward, while accepted replies start empty. The same reply key can
then create a new receipt. The CLI remains an offline alternative.

The next Support increment provides GET `/api/support/inquiries` with `limit`
(1–100, default 50), `offset` (>=0, default 0), and optional nonempty `order_id`
for an exact source reference match. Results are a bare array in inquiry-ID
order, including S12. No matches or an offset past the end returns `[]`.
Filtering occurs before pagination; no Product processing status is inferred.

GET `/api/support/inquiries/{inquiry_id}/replies` uses the same limit/offset
and returns accepted records in insertion order: `reply_id`, `status`, `sent_at`,
`inquiry_id`, `text`, `idempotency_key`. Text is exact, retries return no duplicate
rows, and results are isolated by inquiry. A known inquiry without replies
returns `[]`; an unknown inquiry returns 404. Invalid pagination returns 422.
History persists across restart and clears on reset. Existing POST receipts
and single-inquiry schemas are unchanged.

- This phase uses the requested `/api/...` paths, not the older `/.../v1` paths.
- OMS lists parcels, then the Product retrieves each shipment and event list.
  There is no aggregate order context, HTTP 207, or cross-system partial envelope.
- The current 12 scenario definitions replace the plan's older scenario mapping.
- S12 has an inquiry but deliberately no order. There are 11 golden orders plus
  109 ordinary orders, for a total of 120; golden record identities are unchanged.
- An explicit fixed reference time replaces implicit current reset time for
  exact reproducibility. The default reproduces the original source records.
- No fetched_at is fabricated; null updates remain unknown.
- Full implementation adds API Key, Policy, inventory summary, source customer
  lookup and deterministic ordinary records. Offline CLI reset remains available.
- Existing seed versions are not silently replaced at startup; an explicit
  reset installs sandbox-v2 and clears the previous run.
