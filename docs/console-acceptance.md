# Sandbox console browser acceptance — 2026-10-13

The actual console at `http://127.0.0.1:9010/` was operated in the Codex browser
against a running Uvicorn service. This run used `.console-test.sqlite3`, separate
from the normal application database. Controls were clicked and submitted through
the page; rendered responses, IDs, statuses, disabled states and pagination were
asserted. The run recorded 169 successful assertions after fixing the defects
below. It did not substitute mocked API responses for browser acceptance.

## Coverage

| Visible capability | Accepted behavior |
|---|---|
| Navigation | All four views, brand link returning home, API documentation link opening a rendered Swagger page |
| Connection and metrics | Default key works; blank key returns 401; wrong key returns 403; reconnect restores operation and refreshes the selected conversation |
| S01–S12 | Every scenario inspected; expected independent 200/404/503/504 results, seven panels for the split-parcel case, S12 inquiry available despite missing order |
| Source retry | OMS order, parcel discovery, warehouse, shipment and events read current source writes; new tracking references rebuild dependent panels without refetching other systems |
| Source absences | Null tracking, absent shipment, empty event history and null timestamps displayed without inventing values |
| Customer lookup | Customer query, order selection, ten-row first page, four-row second page, previous page and disabled final-page controls; unknown customer displays 404 |
| Policy | Original facts rendered from the Policy HTTP endpoint |
| Inquiry discovery | OPEN, REPLIED and all-status filters; order filter, empty results, next/previous page; failed requests disable pagination |
| Inquiry creation | Both associated and unassociated orders; blank messages rejected with 422; accepted inquiry automatically opens |
| Customer follow-up | Keep, clear and replace order reference; current customer message and conversation update |
| Simulated replies | Reply binds to latest customer message and changes status to REPLIED; history shows binding |
| Concurrent follow-up | Second browser page submits a new message; stale reply receives 409, refreshes latest message and preserves the draft |
| Long conversation | 52-message fixture; first 50 and remaining two loaded without duplicates; latest customer message visible before loading the entire history |
| Untrusted text | HTML-like customer text displayed literally; no image element or script execution created |
| Fault modes | Every mode applied through the form for both logistics and warehouse, then observed through source reads |
| Fault editing | Edit restores system/record/mode/delay; refresh shows actual configuration and consumed one-shot budget; removal is idempotent and restores S08 baseline failure |
| Source simulation | All eight create/update/append operations accepted; corresponding reads show the returned source records |
| Validation/errors | Invalid JSON, duplicate-source 409, unknown-target 404, naive-source-time 422, invalid zero-delay slow response |
| Reset | Unchecked confirmation prevents reset; current UTC and fixed baseline clocks work; baseline counts, overrides, conversations and old write results restored/cleared |
| Responsive layout | All four views at a 390-pixel viewport; no horizontal overflow, including 157-character order/parcel/tracking IDs |

Fault response checks included NORMAL recovery, one shared TIMEOUT_ONCE failure,
persistent 504/500/429 responses, an actual 250-ms slow response, 72-hour-old source
timestamps, empty arrays/null state, per-record PARTIAL_FAILURE 503, conflicting
facts, and HTTP 200 with malformed JSON explicitly marked as a parsing error.
OMS and the unaffected subsystem remained independently readable.

Customer pagination and history fixtures were prepared through the existing HTTP
source APIs. All fixtures and browser mutations were removed by the console's
fixed-clock reset at the end. Final inventory: 120 orders, 143 parcels, 60
inquiries, zero replies and zero fault overrides. No browser script errors were
recorded. Viewport overrides and auxiliary browser tabs were removed.

## Defects fixed during the run

- Parcel-only retry previously changed the JSON but left obsolete null-tracking
  panels. It now discovers the current tracking references and rebuilds only
  the dependent logistics panels.
- Manual/customer-linked order selection previously left another golden scenario
  highlighted. Inspection now derives the selection from the actual order ID.
- Message pagination reused the reply mutation wrapper and left a permanent
  processing message. It now has its own loading guard and prevents duplicate
  page submissions without altering reply-form status.
- Global connection refresh omitted the open conversation. It now refreshes that
  conversation while preserving its draft; a latest-customer preview prevents
  long histories from concealing the current message.
- Failed list reads now disable stale pagination controls, and obsolete responses
  cannot overwrite a newer customer/inquiry query's failure state.
- Sending remains disabled after failed authentication or while its own write is
  in flight. Reset clears old write receipts and operation messages.
- PARTIAL_FAILURE help now accurately describes a per-record 503, and long source
  IDs wrap in headers and endpoint paths.

## Repeatable regression checks

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python scripts/smoke.py
node --test tests/console_behavior.test.cjs
```

The dependency-free Node tests exercise production console functions/event
handlers with an isolated DOM stub. They cover parcel retry, scenario selection,
history loading guards and idempotency after an interrupted write. They supplement
the real-browser checks; they do not replace them. Node is needed only for these
development checks, not to run the console.
