# Sandbox boundaries

- Build only a fake external ecommerce environment, never AI features.
- No generic SaaS, microservices, or product business logic. The user-authorized
  Sandbox console may inspect and control fake sources through the existing HTTP
  APIs; never add Product workflows or AI features to this console.
- Never aggregate systems into a Product context or implement Product adapters.
- The Product accesses this service only through HTTP.
- Preserve S01-S12 scenario IDs and their stable source IDs.
- External behavior must resemble real APIs, including independent HTTP failures.
- Preserve source timestamps and nulls; never generate fetched_at or freshness.
- Every behavior change requires tests. Run pytest, ruff check, ruff format --check,
  and a real application startup smoke test.
- Full Sandbox implementation includes 120 deterministic orders, the unchanged
  S01-S12 scenarios, source read/reply APIs, Policy facts, independent fault
  controls, HTTP reset, API Key service authentication and container deployment.
- Continuous simulation includes idempotent customer ingress/follow-ups and
  explicit admin writes to individual OMS, Logistics and Warehouse source records.
- Source writes must not automatically advance other subsystems or interpret
  customer text. Preserve history, IDs and source timestamp/null semantics.
- Do not build Product adapters, freshness rules, authorization workflows, AI
  answers, or real ecommerce integrations. Keep the single-service design.
