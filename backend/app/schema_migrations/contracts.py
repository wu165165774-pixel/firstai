from __future__ import annotations

import os

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SchemaAuthority:
    key: str
    filename: str
    environment_variable: str
    default_path: str
    required_columns: dict[str, frozenset[str]]
    required_indexes: frozenset[str]

    def resolve_path(self, data_root: Path | None = None) -> Path:
        if data_root is not None:
            return data_root / self.filename
        return Path(
            os.getenv(self.environment_variable, self.default_path)
        )


def _columns(*names: str) -> frozenset[str]:
    return frozenset(names)


AUTHORITIES = (
    SchemaAuthority(
        key="novels",
        filename="novels.db",
        environment_variable="NOVELFORGE_NOVEL_DB_PATH",
        default_path="/app/data/novels.db",
        required_columns={
            "novel_projects": _columns(
                "novel_id", "user_id", "title", "genre", "premise",
                "language", "target_word_count", "status",
                "style_guide_json", "constraints_json", "metadata_json",
                "revision", "created_at", "updated_at"
            ),
            "story_bibles": _columns(
                "novel_id", "revision", "world_json", "characters_json",
                "factions_json", "locations_json", "rules_json",
                "themes_json", "timeline_json", "metadata_json", "updated_at"
            ),
            "story_bible_revisions": _columns(
                "novel_id", "revision", "snapshot_json", "created_at"
            ),
            "novel_entities": _columns(
                "novel_id", "entity_id", "entity_type",
                "canonical_name", "canonical_name_normalized", "aliases_json",
                "description", "revision", "metadata_json", "created_at",
                "updated_at"
            ),
            "novel_entity_aliases": _columns(
                "novel_id", "entity_id", "alias", "normalized_alias",
                "alias_kind", "created_at"
            ),
            "novel_plans": _columns(
                "novel_id", "revision", "source_project_revision",
                "source_story_bible_revision", "story_premise",
                "core_conflict", "central_question", "ending_direction",
                "themes_json", "main_plot_json", "character_arcs_json",
                "volume_plans_json", "metadata_json", "created_at",
                "updated_at"
            ),
            "novel_plan_revisions": _columns(
                "novel_id", "revision", "snapshot_json", "created_at"
            ),
            "story_arcs": _columns(
                "arc_id", "novel_id", "volume_number", "arc_number",
                "revision", "source_project_revision",
                "source_story_bible_revision", "source_novel_plan_revision",
                "title", "objective", "summary", "opening_state",
                "closing_state", "core_conflict", "stakes",
                "turning_points_json", "character_progression_json",
                "plot_threads_json", "dependencies_json",
                "target_chapter_start", "target_chapter_end", "metadata_json",
                "created_at", "updated_at"
            ),
            "story_arc_revisions": _columns(
                "arc_id", "novel_id", "revision", "snapshot_json",
                "created_at"
            ),
            "chapter_plans": _columns(
                "chapter_plan_id", "novel_id", "arc_id", "chapter_number",
                "revision", "source_project_revision",
                "source_story_bible_revision", "source_novel_plan_revision",
                "source_story_arc_revision", "title", "objective", "summary",
                "pov_character_id", "pov_character_name", "opening_state",
                "closing_state", "conflict", "reveal", "hook",
                "scene_beats_json", "continuity_dependencies_json",
                "target_word_count", "metadata_json", "created_at",
                "updated_at"
            ),
            "chapter_plan_revisions": _columns(
                "chapter_plan_id", "novel_id", "revision", "snapshot_json",
                "created_at"
            ),
            "manuscript_chapters": _columns(
                "manuscript_chapter_id", "novel_id", "chapter_plan_id",
                "chapter_number", "revision", "latest_revision",
                "accepted_revision", "accepted_at", "created_at", "updated_at"
            ),
            "manuscript_revisions": _columns(
                "manuscript_chapter_id", "novel_id", "revision", "content",
                "content_hash", "source_workflow_run_id",
                "source_workflow_version_id", "source_stage",
                "source_round_index", "review_status", "quality_scores_json",
                "review_summary", "source_project_revision",
                "source_story_bible_revision", "source_novel_plan_revision",
                "source_story_arc_id", "source_story_arc_revision",
                "source_chapter_plan_id", "source_chapter_plan_revision",
                "candidate_facts_json", "created_at"
            ),
            "manuscript_fact_projections": _columns(
                "projection_id", "novel_id", "manuscript_chapter_id",
                "manuscript_revision", "chapter_number", "fact_index",
                "fact_id", "fact_json", "operation", "superseded_by_revision",
                "status", "attempts", "memory_id", "memory_projected",
                "vector_projected", "graph_kind", "graph_id",
                "graph_projected", "last_error", "created_at", "updated_at",
                "completed_at"
            ),
        },
        required_indexes=_columns(
            "idx_chapter_plan_revisions_time", "idx_chapter_plans_arc",
            "idx_chapter_plans_order", "idx_entity_alias_resolution",
            "idx_fact_projections_replacement",
            "idx_fact_projections_revision", "idx_fact_projections_status",
            "idx_manuscript_chapters_order", "idx_manuscript_revisions_run",
            "idx_manuscript_revisions_time", "idx_novel_entities_type",
            "idx_novel_plan_revisions_time", "idx_novel_projects_status",
            "idx_novel_projects_user", "idx_story_arc_revisions_time",
            "idx_story_arcs_order", "idx_story_arcs_volume",
            "idx_story_bible_revisions_time",
        ),
    ),
    SchemaAuthority(
        key="workflow",
        filename="workflow_runs.db",
        environment_variable="NOVELFORGE_WORKFLOW_DB_PATH",
        default_path="/app/data/workflow_runs.db",
        required_columns={
            "workflow_runs": _columns(
                "run_id", "root_run_id", "user_id", "novel_id",
                "parent_run_id", "workflow_type", "execution_status",
                "workflow_status", "quality_gate_passed", "resumable",
                "revision_rounds", "request_json", "result_json",
                "latest_content", "error", "created_at", "updated_at",
                "completed_at"
            ),
            "workflow_run_events": _columns(
                "event_id", "run_id", "sequence_no", "event_type",
                "stage", "round_index", "attempt_index", "payload_json",
                "created_at"
            ),
            "workflow_chapter_versions": _columns(
                "version_id", "run_id", "version_index", "source_stage",
                "round_index", "content", "content_hash", "created_at"
            ),
            "workflow_run_jobs": _columns(
                "run_id", "idempotency_key", "queue_status",
                "cancel_requested", "lease_owner", "lease_expires_at",
                "heartbeat_at", "queued_at", "claimed_at", "updated_at",
                "priority", "attempt_count", "max_attempts",
                "retry_base_seconds", "available_at", "last_error",
                "dead_lettered_at", "timeout_seconds", "timed_out_count"
            ),
            "workflow_workers": _columns(
                "worker_id", "worker_status", "capacity", "active_count",
                "started_at", "heartbeat_at", "stopped_at", "metadata_json",
                "control_mode", "control_updated_at"
            ),
            "workflow_queue_counters": _columns(
                "counter_name", "counter_value"
            ),
            "workflow_job_archive": _columns(
                "run_id", "user_id", "novel_id", "queue_status",
                "terminal_at", "archived_at", "snapshot_json"
            ),
            "workflow_operations_audit": _columns(
                "audit_id", "operation_type", "target_type", "action",
                "target_id", "status", "created_at", "details_json"
            ),
            "novel_orchestrations": _columns(
                "orchestration_id", "novel_id", "user_id", "status",
                "revision", "current_sequence_no", "total_chapters",
                "accepted_chapters", "selection_json", "workflow_policy_json",
                "queue_policy_json", "metadata_json", "idempotency_key",
                "paused_from_status", "error", "created_at", "updated_at",
                "completed_at"
            ),
            "novel_orchestration_steps": _columns(
                "orchestration_id", "sequence_no", "chapter_plan_id",
                "chapter_plan_revision", "chapter_number", "chapter_title",
                "arc_id", "arc_revision", "status", "workflow_run_id",
                "workflow_attempt", "manuscript_chapter_id",
                "candidate_revision", "accepted_revision", "error",
                "created_at", "updated_at"
            ),
            "novel_orchestration_events": _columns(
                "event_id", "orchestration_id", "sequence_no", "event_type",
                "chapter_sequence_no", "payload_json", "created_at"
            ),
        },
        required_indexes=_columns(
            "idx_novel_orchestration_events",
            "idx_novel_orchestration_steps_run",
            "idx_novel_orchestrations_list", "idx_workflow_events_run",
            "idx_workflow_job_archive_time", "idx_workflow_job_archive_user",
            "idx_workflow_jobs_lease", "idx_workflow_jobs_schedule",
            "idx_workflow_jobs_status",
            "idx_workflow_operations_audit_time",
            "idx_workflow_operations_audit_type", "idx_workflow_runs_root",
            "idx_workflow_runs_user_novel", "idx_workflow_versions_run",
            "idx_workflow_workers_control", "idx_workflow_workers_status",
        ),
    ),
    SchemaAuthority(
        key="memory",
        filename="memory.db",
        environment_variable="MEMORY_DB_PATH",
        default_path="/app/data/memory.db",
        required_columns={
            "memories": _columns(
                "id", "user_id", "novel_id", "memory_type", "content",
                "importance", "created_at", "metadata", "hit_count",
                "updated_at", "last_accessed_at", "score", "memory_tier",
                "session_id", "expires_at", "revision"
            ),
            "memory_lifecycle_events": _columns(
                "event_id", "memory_id", "user_id", "novel_id",
                "event_type", "from_tier", "to_tier", "reason", "payload",
                "created_at"
            ),
        },
        required_indexes=_columns(
            "idx_memories_expiration", "idx_memories_tier_scope",
            "idx_memory_lifecycle_events",
        ),
    ),
    SchemaAuthority(
        key="external_knowledge",
        filename="external_knowledge.db",
        environment_variable="EXTERNAL_KNOWLEDGE_DB_PATH",
        default_path="/app/data/external_knowledge.db",
        required_columns={
            "external_knowledge_sources": _columns(
                "source_id", "user_id", "knowledge_base_id", "source_uri",
                "source_type", "current_revision", "created_at", "updated_at"
            ),
            "external_knowledge_revisions": _columns(
                "source_id", "revision", "content", "content_hash",
                "title", "author", "published_at", "metadata_json",
                "created_at"
            ),
            "external_knowledge_chunks": _columns(
                "chunk_id", "source_id", "source_revision", "chunk_number",
                "content", "start_char", "end_char", "content_hash",
                "created_at"
            ),
        },
        required_indexes=_columns(
            "idx_external_chunks_current", "idx_external_sources_scope",
        ),
    ),
    SchemaAuthority(
        key="temporal_graph",
        filename="temporal_graph.db",
        environment_variable="NOVELFORGE_TEMPORAL_GRAPH_DB_PATH",
        default_path="/app/data/temporal_graph.db",
        required_columns={
            "temporal_events": _columns(
                "event_id", "novel_id", "event_type", "context_type",
                "title", "summary", "location_entity_id", "start_chapter",
                "end_chapter", "source_type", "source_id", "source_revision",
                "source_chapter_number", "confidence", "metadata_json",
                "revision", "created_at", "updated_at"
            ),
            "temporal_event_participants": _columns(
                "event_id", "entity_id", "participant_order"
            ),
            "temporal_event_revisions": _columns(
                "event_id", "novel_id", "revision", "snapshot_json",
                "created_at"
            ),
            "temporal_relations": _columns(
                "relation_id", "novel_id", "subject_entity_id", "predicate",
                "object_entity_id", "context_type", "description",
                "valid_from_chapter", "valid_to_chapter", "source_type",
                "source_id", "source_revision", "source_chapter_number",
                "confidence", "metadata_json", "revision", "created_at",
                "updated_at"
            ),
            "temporal_relation_revisions": _columns(
                "relation_id", "novel_id", "revision", "snapshot_json",
                "created_at"
            ),
        },
        required_indexes=_columns(
            "idx_temporal_events_scope", "idx_temporal_events_source",
            "idx_temporal_participants_entity",
            "idx_temporal_relations_entities",
            "idx_temporal_relations_scope", "idx_temporal_relations_source",
        ),
    ),
)

AUTHORITIES_BY_KEY = {item.key: item for item in AUTHORITIES}
