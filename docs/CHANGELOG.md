# Changelog

## Unreleased
- Added Sprint 03A LLM Core framework.

## v0.15.0-alpha.26

- Added an independent SQLite Temporal Graph authority for events, relations, normalized participants, chapter-valid intervals, and immutable revision snapshots.
- Enforced canonical entity references plus exact Story Bible or accepted Manuscript source revisions without automatic fact extraction or persistence.
- Added current/historical Graph APIs, deterministic entity/time-aware retrieval, and optimistic concurrency with HTTP 409 conflicts.
- Replaced the placeholder Graph lane with the real Temporal Graph provider while preserving Vector-only degradation for unavailable scopes.
- Forwarded active entities and chapter coordinates through Memory Context, Chat, Novel Agent, and grounded specialized Agents.
- Added real Graph/Vector fusion and local `qwen3:8b` acceptance plus 390-test regression coverage.

## v0.15.0-alpha.25

- Added concurrent Vector/Graph retrieval lanes with independent timeout, failure isolation, and explicit degradation diagnostics.
- Added deterministic reciprocal-rank fusion, normalized-content deduplication, provenance, `top_k`, and character-budget enforcement.
- Reused Working/Long-term Hybrid Memory for the Vector lane while keeping Session Memory exact-scoped in SQLite.
- Integrated fused retrieval diagnostics into Memory Context, Novel Agent, Chat, and grounded specialized Agents.
- Kept Temporal Graph persistence out of Sprint 08C.3; the default Graph lane reports unavailable until Sprint 08D.1.
- Added real local Qwen Embedding and `qwen3:8b` acceptance plus 370-test regression coverage.

## v0.15.0-alpha.24

- Added a physically isolated External Knowledge SQLite database and FAISS namespace.
- Added scoped source CRUD, immutable revisions, deterministic chunks, optimistic concurrency, and startup index repair.
- Added traceable `EK:<source>:r<revision>:c<chunk>` citations with response-boundary normalization.
- Added opt-in P6 External Knowledge context for Novel Agent and Chat without contaminating novel Memory.
- Added real local Qwen Embedding/Qwen Agent acceptance for scope isolation, prompt-injection resistance, citations, and restart persistence.

## v0.15.0-alpha.23

- Added independent Session, Working, and Long-term lifecycle tiers without changing content-type taxonomy.
- Added stable memory revisions, append-only lifecycle events, adjacent promotion gates, TTL sweep, and session close.
- Kept Session memory out of FAISS while indexing Working and Long-term evidence with tier-aware retrieval/context.
- Migrated legacy memories to Long-term and preserved existing Memory/Agent API contracts.
- Fixed duplicate `MemoryExtractor` persistence and added real Qwen Embedding lifecycle acceptance coverage.

## v0.15.0-alpha.22

- Added persisted whole-novel orchestrations with frozen Chapter Plan revision order.
- Added one-chapter-at-a-time Workflow queueing, explicit reconciliation, and accepted-only continuity handoff.
- Preserved the Manuscript human gate: successful Workflow output is imported as a candidate but never auto-accepted.
- Added optimistic orchestration revisions, append-only events, pause/resume, retry, idempotent creation, and restart recovery.
- Added Orchestrator API/OpenAPI coverage plus real two-chapter external-worker `qwen3:8b` acceptance.

## v0.15.0-alpha.21

- Added stable Manuscript Chapter aggregates and append-only manuscript revisions.
- Added explicit import of successful quality-gated Workflow Runs as reviewed candidates.
- Added explicit, optimistic-concurrency Manuscript acceptance with transactional stale-source guards.
- Added accepted-only prior Manuscript continuity to bounded Chapter Workflow Grounding.
- Added Manuscript API, persistence, OpenAPI, restart, idempotency, and real `qwen3:8b` acceptance coverage.

## v0.15.0-alpha.20

- Bound every new Chapter Workflow execution to a fresh Chapter Plan revision.
- Added bounded Project/Bible/Plan/Arc/Chapter grounding for Chapter, Review, and Rewrite.
- Revalidated bindings during synchronous runs, resume, queue admission, and external Worker execution.
- Added safe Qwen Review retry behavior for truncated structured output.

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
