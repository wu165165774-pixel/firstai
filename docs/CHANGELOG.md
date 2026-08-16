# Changelog

## Unreleased
- Added Sprint 03A LLM Core framework.

## v0.15.0-alpha.37

- Added deterministic, in-memory novel ZIP exports containing current Project, Story Bible, entity registry, Novel Plan, Story Arcs, Chapter Plans, and accepted Manuscript only.
- Added a versioned manifest with per-member byte counts and SHA-256 hashes, accepted-source revision provenance, and an out-of-band manifest checksum response header.
- Added optimistic snapshot conflict detection, accepted-content integrity validation, strict novel/user isolation, and candidate Manuscript exclusion.
- Added an authenticated workbench download action and a production HTTP export drill that verifies every member and repeat-download determinism without retaining temporary archives.

## v0.15.0-alpha.36

- Added explicit schema version 1 contracts for all five authoritative SQLite databases, covering complete business table, column, and named-index sets.
- Added read-only status, backup-gated offline upgrade, strict verification, per-authority migration ledgers, fixed checksums, and idempotent reruns.
- Added historical schema bootstrap, transactional per-database rollback, incomplete-schema and tampered-ledger rejection, and newer-database fail-closed startup guards.
- Added a PowerShell maintenance workflow that rehearses migration on an isolated restored copy before upgrading production authorities.

## v0.15.0-alpha.35

- Added an offline multi-store backup CLI for the five authoritative SQLite databases and two FAISS index/mapping pairs.
- Added strict manifests with SHA-256, SQLite integrity/schema metadata, load-tested FAISS dimension/count metadata, and explicit rebuild state.
- Added fail-closed path/layout validation, backup verification, dry-run-by-default restore, and new-directory-only recovery without in-place production overwrite.
- Added a manifest-last finalization fallback for Windows bind mounts that reject atomic directory replacement.
- Added backup/restore operator documentation and focused tests while centralizing the Backend application version.

## v0.15.0-alpha.34

- Added configurable OpenAI, Anthropic Claude, and Alibaba Cloud Model Studio/DashScope chat Provider adapters without changing business-layer contracts.
- Added async non-streaming and SSE streaming mappings, token usage normalization, model overrides, and bounded non-billable Models API health probes.
- Registered honest cloud capabilities and configuration state in the Provider catalog while keeping API keys and endpoints out of responses and logs.
- Added official Anthropic SDK dependency, empty-key environment examples, 14 Provider-focused tests, full backend/frontend regression, and local Qwen availability verification.

## v0.15.0-alpha.33

- Added a revisioned Prompt catalog with deterministic current/explicit revision resolution for Agent, Consistency, and Memory prompt identities.
- Recorded trusted system-prompt and fully assembled provider-visible request SHA-256 provenance without exposing prompt content.
- Propagated prompt provenance through Agent and Planner results, persisted Workflow step metadata, Consistency analysis responses, and extracted Memory metadata.
- Replaced client/provider-supplied provenance at the Agent boundary so audit identity cannot be forged through request or response metadata.
- Displayed selected Prompt revisions in Planner candidate and Workflow inspector views, with backend/frontend regression and real Qwen candidate-only acceptance.

## v0.15.0-alpha.32

- Added a backward-compatible Provider catalog that reports capabilities and distinguishes registered, configured, and currently available states.
- Added explicit, bounded, concurrent health probes with sanitized errors and no secret or endpoint disclosure.
- Made local Qwen endpoint/model and DeepSeek endpoint/model/key configuration authoritative; fixed the DeepSeek settings attribute mismatch and zero-temperature handling.
- Added Provider/Model catalog selection to the Vue Workflow form with configuration and live availability labels plus an offline fallback.
- Added Provider-focused backend and frontend coverage, real Ollama catalog acceptance, and production frontend image verification.

## v0.15.0-alpha.31

- Added opt-in Bearer authentication backed by operator-configured token-to-user and role mappings, with fail-closed validation when enabled.
- Bound declared request identity and existing Novel, Workflow Run, and Memory ownership to the authenticated user while hiding cross-user resources behind HTTP 404.
- Restricted global queue, Worker, dead-letter, operations, and Prometheus endpoints to the `admin` role and rejected unscoped project/Workflow listings.
- Added `/api/v1/auth/me`, OpenAPI Bearer security declarations, a public health exception, and a session-only workbench token input.
- Added Compose and `.env.example` configuration without committing secrets.

## v0.15.0-alpha.30

- Added Story Bible, Novel Plan, Story Arc, and Chapter Plan domain editors with structured fields, advanced JSON sections, revision display, and optimistic save semantics.
- Added local Qwen Planner candidate generation, editable candidate review, explicit acceptance, source revision display, and client-side stale/fixed-coordinate gates without bypassing backend validation.
- Added new Story Arc and Chapter Plan creation flows while keeping existing entities on their independent stable IDs and revisioned PUT APIs.
- Added a grounded single-chapter Workflow form that binds the exact fresh Chapter Plan revision and submits through the persistent async queue with idempotency and priority headers.
- Added deterministic planning payload/coordinate tests and async Workflow API tests, bringing the frontend suite to 14 tests.
- Fixed the frontend container healthcheck to use the explicit IPv4 loopback address and verified the production container reaches `healthy`.
- Verified real Qwen Novel Plan, Story Arc, and Chapter Plan candidate-only/accept flows plus direct stale propagation/repair and idempotent Workflow queueing through the Nginx workbench proxy.

## v0.15.0-alpha.29

- Added the Vue 3 creation workbench with user-scoped Project library, six-stage planning/production overview, and responsive desktop/mobile layouts.
- Added Chapter Plan, Workflow Run, and whole-novel Orchestration operations without bypassing freshness, quality, or human acceptance gates.
- Added Manuscript revision review, optimistic explicit acceptance, frozen fact display, per-sink projection checkpoints, and safe retry controls.
- Added a typed frontend API client, deterministic helpers, API/pure-function tests, and single-process Vue bundle verification.
- Added a reproducible Node/Vite-to-Nginx image, same-origin Backend proxy, SPA fallback, static caching, healthcheck, and Compose service on host port `18081`.
- Verified the retained 08D.3 Project through the workbench API surface, production Docker runtime, 8 frontend tests, and 434 backend regression tests.

## v0.15.0-alpha.28

- Froze reviewed candidate facts into immutable Manuscript revisions and atomically enqueued projection outbox items only when an approved revision was explicitly accepted.
- Added idempotent, checkpointed projection into Long-term Memory, FAISS Vector, and Temporal Graph with exact accepted-Manuscript provenance.
- Added retry, startup recovery, failed-sink repair, and safe retraction/reactivation when an accepted Manuscript revision is replaced or selected again.
- Added chapter-valid relationship, life-state, and location transition handling while keeping character belief isolated from world-state constraints.
- Added fact-projection status/retry APIs with strict novel/chapter/revision scope validation.
- Added real `qwen3:8b` Workflow-to-Manuscript acceptance, dual-lane retrieval, restart persistence, and 434-test regression coverage.

## v0.15.0-alpha.27

- Added bounded, provenance-preserving pre-writing constraints from Project, Story Bible, Canonical Entity Registry, and chapter-valid Temporal Graph state.
- Added structured Qwen candidate-fact extraction plus deterministic identity, relationship, life-state, location, timeline, evidence, and knowledge-scope checks.
- Added three candidate-only Consistency APIs with strict user/novel isolation and no Graph, Memory, Vector, Canon, or Manuscript writes.
- Integrated deterministic consistency conflicts into Chapter Review, Rewrite, and Re-review so confirmed blocking conflicts cannot pass the quality gate.
- Bound extractor and grounded Review chapter coordinates to the authoritative request/Chapter Plan coordinate.
- Added real `qwen3:8b` conflict acceptance and 408-test regression coverage.

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
