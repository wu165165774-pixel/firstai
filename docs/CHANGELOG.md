# Changelog

## Unreleased
- Added Sprint 03A LLM Core framework.

## v0.15.0-alpha.19

- Added explicit legacy Story Bible character alignment to canonical entity IDs.
- Added transaction-safe ambiguity, duplicate binding, ID/name, and revision conflicts.
- Added canonical planning reference validation for Novel Plan, Story Arc, and Chapter Plan.
- Added bounded P0 Canon Context injection ahead of Memory/RAG evidence.
- Added Canon revision invalidation when canonical entities change.
- Revalidated all three Planner targets with real `qwen3:8b` and canonical IDs.

## v0.15.0-alpha.18

- Added the Sprint 08A.7 canonical Entity Registry with stable novel-scoped IDs.
- Added deterministic exact/normalized Alias Resolver results with explicit ambiguity candidates.
- Added entity revision conflicts, alias-index rebuilds, API routes, and restart persistence.
- Added the long-form consistency audit and phased P0/P1/P2 implementation route.

## v0.15.0-alpha.17

- Added explicit Planner candidate acceptance through `/planner/accept`.
- Added stale candidate source-revision conflicts and transaction-level source guards.
- Preserved candidate-only generation, fixed coordinates, stale gates, and no-Planner-table boundary.
- Added the canonical product and engineering Roadmap.
