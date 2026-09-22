# Sandbox boundaries

- Build only a fake external ecommerce environment, never AI features.
- No generic SaaS, microservices, UI, or product business logic.
- Never aggregate systems into a Product context or implement Product adapters.
- The Product accesses this service only through HTTP.
- Preserve S01-S12 scenario IDs and their stable source IDs.
- External behavior must resemble real APIs, including independent HTTP failures.
- Preserve source timestamps and nulls; never generate fetched_at or freshness.
- Every behavior change requires tests. Run pytest, ruff check, ruff format --check,
  and a real application startup smoke test.
- Current scope is S0-S1 as documented in README and docs/api-contract.md.
