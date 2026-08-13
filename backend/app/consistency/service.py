from __future__ import annotations

import hashlib
import json
import re
import unicodedata

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.llm.bootstrap import llm_manager
from app.llm.manager import LLMManager
from app.llm.schemas import ChatMessage, ChatRequest
from app.novels.schemas import EntityResolveRequest, NovelEntity
from app.novels.service import NovelProjectService
from app.novels.storage import NovelProjectNotFoundError
from app.planner.parser import PlannerOutputError, extract_json_object
from app.temporal_graph.storage import TemporalGraphStorage

from .schemas import (
    ConsistencyAnalyzeRequest,
    ConsistencyAnalyzeResult,
    ConsistencyCheckRequest,
    ConsistencyCheckResult,
    ConsistencyConflict,
    ConsistencyConstraint,
    ConsistencyConstraintRequest,
    ConsistencyFactCandidate,
    ConsistencySource,
)


class ConsistencyOutputError(ValueError):
    pass


class _ExtractedFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_facts: list[ConsistencyFactCandidate] = Field(
        default_factory=list,
        max_length=200,
    )


class ConsistencyEngine:
    """Deterministic pre/post writing consistency boundary."""

    CONSTRAINT_SCAN_LIMIT = 200
    DEFAULT_CONTEXT_BUDGET = 3600

    _RELATION_GROUPS = {
        "ally": {
            "ally",
            "allies",
            "allied",
            "friend",
            "friends",
            "盟友",
            "同盟",
            "友好",
        },
        "hostile": {
            "enemy",
            "enemies",
            "enmity",
            "foe",
            "foes",
            "adversary",
            "adversaries",
            "hostile",
            "rival",
            "敌对",
            "敌人",
            "仇敌",
        },
    }
    _INCOMPATIBLE_RELATION_GROUPS = {frozenset(("ally", "hostile"))}
    _DEAD_TERMS = {"death", "dead", "dies", "died", "死亡", "去世", "身亡"}
    _ALIVE_TERMS = {
        "alive",
        "resurrection",
        "revived",
        "存活",
        "复活",
        "苏醒",
    }
    _TRANSITION_TERMS = {
        "relationship": {
            "became",
            "become",
            "turned",
            "broke alliance",
            "formed an alliance",
            "成为",
            "转为",
            "决裂",
            "结盟",
            "背叛",
        },
        "life_state": {
            "died",
            "dies",
            "revived",
            "resurrected",
            "死亡",
            "身亡",
            "复活",
            "苏醒",
        },
        "location": {
            "moved",
            "arrived",
            "left",
            "entered",
            "前往",
            "抵达",
            "离开",
            "进入",
            "移动",
        },
        "identity": {
            "revealed",
            "transformed",
            "renamed",
            "揭示",
            "变成",
            "改名",
        },
        "event": {
            "happened",
            "occurred",
            "began",
            "ended",
            "发生",
            "开始",
            "结束",
        },
        "knowledge": {
            "learned",
            "discovered",
            "was told",
            "得知",
            "发现",
            "获悉",
            "被告知",
        },
    }

    def __init__(
        self,
        novel_service: NovelProjectService | None = None,
        temporal_storage: TemporalGraphStorage | None = None,
        llm_manager_instance: LLMManager | None = None,
    ) -> None:
        self.novel_service = novel_service or NovelProjectService()
        self.temporal_storage = temporal_storage or TemporalGraphStorage()
        self.llm_manager = llm_manager_instance or llm_manager

    def _validate_scope(self, novel_id: str, user_id: str) -> None:
        project = self.novel_service.get_project(novel_id)
        if project.user_id != user_id:
            raise NovelProjectNotFoundError(
                f"Novel Project not found: {novel_id}"
            )

    @staticmethod
    def _statement(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _constraint_text(value: Any) -> str:
        text = ConsistencyEngine._statement(value)
        return text if len(text) <= 8000 else text[:7999].rstrip() + "…"

    @staticmethod
    def _excerpt(value: Any) -> str:
        text = ConsistencyEngine._statement(value)
        return text if len(text) <= 4000 else text[:3999].rstrip() + "…"

    @staticmethod
    def _scope_from_metadata(metadata: dict[str, Any]) -> str:
        value = str(metadata.get("knowledge_scope") or "WORLD_TRUTH")
        if value not in {
            "WORLD_TRUTH",
            "CHARACTER_KNOWLEDGE",
            "CHARACTER_BELIEF",
            "READER_KNOWLEDGE",
        }:
            return "WORLD_TRUTH"
        return value

    @staticmethod
    def _knowers(metadata: dict[str, Any]) -> list[str]:
        values = metadata.get("knower_entity_ids", [])
        if not values and metadata.get("knowledge_holder_entity_id"):
            values = [metadata["knowledge_holder_entity_id"]]
        if not isinstance(values, list):
            return []
        return list(
            dict.fromkeys(
                str(value).strip()
                for value in values
                if str(value).strip()
            )
        )[:100]

    def build_constraints(
        self,
        novel_id: str,
        payload: ConsistencyConstraintRequest,
    ) -> ConsistencyCheckResult:
        self._validate_scope(novel_id, payload.user_id)
        project = self.novel_service.get_project(novel_id)
        bible = self.novel_service.get_story_bible(novel_id)
        constraints: list[ConsistencyConstraint] = []

        for index, statement in enumerate(project.constraints):
            text = self._constraint_text(statement)
            if not text:
                continue
            constraints.append(
                ConsistencyConstraint(
                    constraint_id=f"project:{novel_id}:constraint:{index}",
                    category="world_rule",
                    severity="critical",
                    statement=text,
                    source=ConsistencySource(
                        source_type="novel_project",
                        source_id=novel_id,
                        revision=project.revision,
                        excerpt=self._excerpt(text),
                    ),
                )
            )

        for index, rule in enumerate(bible.rules):
            text = self._constraint_text(rule)
            if not text:
                continue
            constraints.append(
                ConsistencyConstraint(
                    constraint_id=f"bible:{novel_id}:rule:{index}",
                    category="world_rule",
                    severity="critical",
                    statement=text,
                    source=ConsistencySource(
                        source_type="story_bible",
                        source_id=novel_id,
                        revision=bible.revision,
                        excerpt=self._excerpt(text),
                    ),
                )
            )

        active_ids = list(dict.fromkeys(payload.active_entity_ids))
        if payload.pov_character_id and payload.pov_character_id not in active_ids:
            active_ids.append(payload.pov_character_id)
        entities = (
            [self.novel_service.get_entity(novel_id, item) for item in active_ids]
            if active_ids
            else self.novel_service.list_entities(
                novel_id,
                limit=self.CONSTRAINT_SCAN_LIMIT,
            )
        )
        for entity in entities[: self.CONSTRAINT_SCAN_LIMIT]:
            aliases = "、".join(entity.aliases)
            statement = (
                f"{entity.entity_id} 是 {entity.entity_type} 实体"
                f"“{entity.canonical_name}”"
            )
            if aliases:
                statement += f"，别名：{aliases}"
            if entity.description:
                statement += f"；{entity.description}"
            statement = self._constraint_text(statement)
            constraints.append(
                ConsistencyConstraint(
                    constraint_id=f"entity:{entity.entity_id}:r{entity.revision}",
                    category="identity",
                    severity="critical",
                    statement=statement,
                    entity_ids=[entity.entity_id],
                    source=ConsistencySource(
                        source_type="canonical_entity",
                        source_id=entity.entity_id,
                        revision=entity.revision,
                        excerpt=self._excerpt(statement),
                    ),
                )
            )

        events = self.temporal_storage.list_events(
            novel_id,
            active_entity_ids=active_ids,
            as_of_chapter=payload.chapter_number,
            include_historical=False,
            limit=self.CONSTRAINT_SCAN_LIMIT,
        )
        for event in events:
            entity_ids = list(event.participant_entity_ids)
            if event.location_entity_id:
                entity_ids.append(event.location_entity_id)
            statement = f"事件“{event.title}”在第 {event.start_chapter} 章起有效"
            if event.end_chapter is not None:
                statement += f"，至第 {event.end_chapter} 章"
            if event.summary:
                statement += f"：{event.summary}"
            statement = self._constraint_text(statement)
            constraints.append(
                ConsistencyConstraint(
                    constraint_id=f"event:{event.event_id}:r{event.revision}",
                    category=(
                        "life_state"
                        if self._event_life_state(event)
                        else "timeline"
                    ),
                    severity="major",
                    statement=statement,
                    entity_ids=list(dict.fromkeys(entity_ids)),
                    knowledge_scope=self._scope_from_metadata(event.metadata),
                    knower_entity_ids=self._knowers(event.metadata),
                    valid_from_chapter=event.start_chapter,
                    valid_to_chapter=event.end_chapter,
                    source=ConsistencySource(
                        source_type="temporal_event",
                        source_id=event.event_id,
                        revision=event.revision,
                        excerpt=self._excerpt(statement),
                    ),
                )
            )

        relations = self.temporal_storage.list_relations(
            novel_id,
            active_entity_ids=active_ids,
            as_of_chapter=payload.chapter_number,
            include_historical=False,
            limit=self.CONSTRAINT_SCAN_LIMIT,
        )
        for relation in relations:
            statement = (
                f"{relation.subject_entity_id} —{relation.predicate}→ "
                f"{relation.object_entity_id}"
            )
            if relation.description:
                statement += f"：{relation.description}"
            statement = self._constraint_text(statement)
            constraints.append(
                ConsistencyConstraint(
                    constraint_id=(
                        f"relation:{relation.relation_id}:r{relation.revision}"
                    ),
                    category="relationship",
                    severity="major",
                    statement=statement,
                    entity_ids=[
                        relation.subject_entity_id,
                        relation.object_entity_id,
                    ],
                    knowledge_scope=self._scope_from_metadata(relation.metadata),
                    knower_entity_ids=self._knowers(relation.metadata),
                    valid_from_chapter=relation.valid_from_chapter,
                    valid_to_chapter=relation.valid_to_chapter,
                    source=ConsistencySource(
                        source_type="temporal_relation",
                        source_id=relation.relation_id,
                        revision=relation.revision,
                        excerpt=self._excerpt(statement),
                    ),
                )
            )

        category_order = {
            "world_rule": 0,
            "identity": 1,
            "life_state": 2,
            "location": 3,
            "relationship": 4,
            "timeline": 5,
            "knowledge_scope": 6,
        }
        severity_order = {
            "critical": 0,
            "major": 1,
            "moderate": 2,
            "minor": 3,
        }
        constraints.sort(
            key=lambda item: (
                severity_order[item.severity],
                category_order[item.category],
                item.constraint_id,
            )
        )
        context = self.render_constraints(constraints, payload.char_budget)
        return ConsistencyCheckResult(
            novel_id=novel_id,
            chapter_number=payload.chapter_number,
            constraints=constraints,
            persisted=False,
            constraint_context=context,
        )

    @staticmethod
    def render_constraints(
        constraints: list[ConsistencyConstraint],
        char_budget: int = DEFAULT_CONTEXT_BUDGET,
    ) -> str:
        prefix = (
            "[CONSISTENCY CONSTRAINTS - MUST FOLLOW]\n"
            "These are deterministic P0.4 pre-writing constraints. "
            "Do not override them with Memory/RAG or invent repairs.\n"
        )
        result = prefix
        for item in constraints:
            line_prefix = (
                f"- [{item.category}|{item.severity}|"
                f"{item.knowledge_scope}] "
            )
            line_suffix = (
                f"[source={item.source.source_type}:"
                f"{item.source.source_id}:r{item.source.revision or 0}]\n"
            )
            available = (
                char_budget
                - len(result)
                - len(line_prefix)
                - len(line_suffix)
            )
            if available <= 1:
                break
            statement = item.statement
            if len(statement) > available:
                statement = statement[: available - 1].rstrip() + "…"
            result += line_prefix + statement + " " + line_suffix
        return result.rstrip() if len(result) > len(prefix) else ""

    @staticmethod
    def _normalize(value: str) -> str:
        return unicodedata.normalize(
            "NFKC",
            " ".join(str(value or "").split()),
        ).casefold()

    @classmethod
    def _relation_group(cls, predicate: str) -> str | None:
        normalized = cls._normalize(predicate)
        tokens = set(re.findall(r"[a-z0-9_]+", normalized))
        for group, values in cls._RELATION_GROUPS.items():
            for value in values:
                if normalized == value:
                    return group
                if value.isascii() and value in tokens:
                    return group
                if not value.isascii() and value in normalized:
                    return group
        return None

    @classmethod
    def _life_state(cls, value: str) -> str | None:
        normalized = cls._normalize(value)
        tokens = set(re.findall(r"[\w\u3400-\u9fff]+", normalized))
        if tokens.intersection(cls._DEAD_TERMS) or any(
            term in normalized for term in cls._DEAD_TERMS
        ):
            return "dead"
        if tokens.intersection(cls._ALIVE_TERMS) or any(
            term in normalized for term in cls._ALIVE_TERMS
        ):
            return "alive"
        return None

    @classmethod
    def _event_life_state(cls, event: Any) -> str | None:
        return cls._life_state(
            f"{event.event_type} {event.title}"
        ) or cls._life_state(event.summary)

    @classmethod
    def _is_explicit_transition(
        cls,
        fact: ConsistencyFactCandidate,
    ) -> bool:
        if fact.change_type != "transition":
            return False
        normalized = cls._normalize(fact.evidence)
        groups = [fact.fact_type]
        if fact.knowledge_scope == "CHARACTER_KNOWLEDGE":
            groups.append("knowledge")
        return any(
            term in normalized
            for group in groups
            for term in cls._TRANSITION_TERMS.get(group, set())
        )

    @staticmethod
    def _fact_id(fact: ConsistencyFactCandidate, index: int) -> str:
        return fact.fact_id.strip() or f"FACT-{index:03d}"

    @staticmethod
    def _source_for_generated(
        fact: ConsistencyFactCandidate,
    ) -> ConsistencySource:
        return ConsistencySource(
            source_type="generated_text",
            source_id=fact.fact_id,
            excerpt=fact.evidence,
        )

    @staticmethod
    def _conflict_id(fact_id: str, conflict_type: str, expected: str) -> str:
        digest = hashlib.sha256(
            f"{fact_id}|{conflict_type}|{expected}".encode("utf-8")
        ).hexdigest()[:12]
        return f"CONFLICT-{digest}"

    def _conflict(
        self,
        fact: ConsistencyFactCandidate,
        *,
        conflict_type: str,
        severity: str,
        status: str = "confirmed",
        blocking: bool = True,
        message: str,
        expected: str,
        generated: str,
        recommendation: str,
        entity_ids: list[str] | None = None,
        evidence: list[ConsistencySource] | None = None,
    ) -> ConsistencyConflict:
        return ConsistencyConflict(
            conflict_id=self._conflict_id(
                fact.fact_id,
                conflict_type,
                expected,
            ),
            conflict_type=conflict_type,
            severity=severity,
            status=status,
            blocking=blocking,
            message=message,
            expected=expected,
            generated=generated,
            recommendation=recommendation,
            entity_ids=list(dict.fromkeys(entity_ids or [])),
            candidate_fact_id=fact.fact_id,
            evidence=evidence or [],
        )

    def _resolve_entity(
        self,
        novel_id: str,
        fact: ConsistencyFactCandidate,
        *,
        entity_id: str | None,
        name: str | None,
        role: str,
    ) -> tuple[NovelEntity | None, list[ConsistencyConflict]]:
        conflicts: list[ConsistencyConflict] = []
        entity: NovelEntity | None = None
        if entity_id:
            try:
                entity = self.novel_service.get_entity(novel_id, entity_id)
            except NovelProjectNotFoundError:
                conflicts.append(
                    self._conflict(
                        fact,
                        conflict_type="unknown_entity",
                        severity="critical",
                        message=f"{role} entity does not exist: {entity_id}",
                        expected="A canonical entity ID in this novel",
                        generated=entity_id,
                        recommendation="Use an existing canonical entity ID.",
                    )
                )
                return None, conflicts
            if name:
                valid_names = {
                    self._normalize(entity.canonical_name),
                    *(self._normalize(item) for item in entity.aliases),
                }
                if self._normalize(name) not in valid_names:
                    conflicts.append(
                        self._conflict(
                            fact,
                            conflict_type="identity_mismatch",
                            severity="critical",
                            message=(
                                f"{role} name does not identify {entity.entity_id}."
                            ),
                            expected=entity.canonical_name,
                            generated=name,
                            recommendation=(
                                "Use the canonical name or a registered alias."
                            ),
                            entity_ids=[entity.entity_id],
                            evidence=[
                                ConsistencySource(
                                    source_type="canonical_entity",
                                    source_id=entity.entity_id,
                                    revision=entity.revision,
                                    excerpt=entity.canonical_name,
                                )
                            ],
                        )
                    )
            return entity, conflicts

        assert name is not None
        resolution = self.novel_service.resolve_entity(
            novel_id,
            EntityResolveRequest(name=name),
        )
        if resolution.status == "resolved":
            return resolution.entity, conflicts
        if resolution.status == "ambiguous":
            conflicts.append(
                self._conflict(
                    fact,
                    conflict_type="ambiguous_alias",
                    severity="critical",
                    message=f"{role} name is ambiguous: {name}",
                    expected="One unambiguous canonical entity",
                    generated=name,
                    recommendation="Replace the name with a stable entity ID.",
                    entity_ids=[item.entity_id for item in resolution.candidates],
                    evidence=[
                        ConsistencySource(
                            source_type="canonical_entity",
                            source_id=item.entity_id,
                            revision=item.revision,
                            excerpt=item.canonical_name,
                        )
                        for item in resolution.candidates
                    ],
                )
            )
        else:
            conflicts.append(
                self._conflict(
                    fact,
                    conflict_type="unknown_entity",
                    severity="critical",
                    message=f"{role} entity cannot be resolved: {name}",
                    expected="A canonical entity or registered alias",
                    generated=name,
                    recommendation="Resolve or create the entity before acceptance.",
                )
            )
        return None, conflicts

    def _check_fact(
        self,
        novel_id: str,
        chapter_number: int,
        constraints: list[ConsistencyConstraint],
        fact: ConsistencyFactCandidate,
    ) -> list[ConsistencyConflict]:
        conflicts: list[ConsistencyConflict] = []
        subject, subject_conflicts = self._resolve_entity(
            novel_id,
            fact,
            entity_id=fact.subject_entity_id,
            name=fact.subject_name,
            role="subject",
        )
        conflicts.extend(subject_conflicts)
        obj: NovelEntity | None = None
        if fact.object_entity_id or fact.object_name:
            obj, object_conflicts = self._resolve_entity(
                novel_id,
                fact,
                entity_id=fact.object_entity_id,
                name=fact.object_name,
                role="object",
            )
            conflicts.extend(object_conflicts)
        if conflicts:
            return conflicts

        assert subject is not None
        explicit_transition = self._is_explicit_transition(fact)
        fact.subject_entity_id = subject.entity_id
        fact.subject_name = fact.subject_name or subject.canonical_name
        if obj is not None:
            fact.object_entity_id = obj.entity_id
            fact.object_name = fact.object_name or obj.canonical_name

        if fact.chapter_number is not None and fact.chapter_number != chapter_number:
            conflicts.append(
                self._conflict(
                    fact,
                    conflict_type="timeline_conflict",
                    severity="major",
                    message="Candidate fact chapter does not match the review chapter.",
                    expected=f"chapter {chapter_number}",
                    generated=f"chapter {fact.chapter_number}",
                    recommendation="Use the current chapter coordinate.",
                    entity_ids=[subject.entity_id],
                )
            )

        identity_predicate = self._normalize(fact.predicate)
        if (
            fact.fact_type == "identity"
            and fact.value
            and identity_predicate
            in {"name", "canonical_name", "entity_type", "名称", "类型"}
        ):
            valid = {
                self._normalize(subject.entity_type),
                self._normalize(subject.canonical_name),
                *(self._normalize(item) for item in subject.aliases),
            }
            if self._normalize(fact.value) not in valid:
                conflicts.append(
                    self._conflict(
                        fact,
                        conflict_type="identity_mismatch",
                        severity="critical",
                        message="Generated identity contradicts the entity registry.",
                        expected=(
                            f"{subject.canonical_name} ({subject.entity_type})"
                        ),
                        generated=fact.value,
                        recommendation="Restore the canonical identity.",
                        entity_ids=[subject.entity_id],
                        evidence=[
                            ConsistencySource(
                                source_type="canonical_entity",
                                source_id=subject.entity_id,
                                revision=subject.revision,
                                excerpt=subject.canonical_name,
                            )
                        ],
                    )
                )

        checks_world_state = fact.knowledge_scope != "CHARACTER_BELIEF"

        if (
            fact.fact_type == "relationship"
            and obj is not None
            and checks_world_state
        ):
            relations = self.temporal_storage.list_relations(
                novel_id,
                active_entity_ids=[subject.entity_id, obj.entity_id],
                as_of_chapter=chapter_number,
                include_historical=False,
                limit=self.CONSTRAINT_SCAN_LIMIT,
            )
            candidate_group = self._relation_group(fact.predicate)
            relevant = [
                item
                for item in relations
                if self._scope_from_metadata(item.metadata)
                != "CHARACTER_BELIEF"
                and (
                    (
                        item.subject_entity_id == subject.entity_id
                        and item.object_entity_id == obj.entity_id
                    )
                    or (
                        candidate_group in {"ally", "hostile"}
                        and item.subject_entity_id == obj.entity_id
                        and item.object_entity_id == subject.entity_id
                    )
                )
            ]
            for relation in relevant:
                existing_group = self._relation_group(relation.predicate)
                if (
                    candidate_group
                    and existing_group
                    and frozenset((candidate_group, existing_group))
                    in self._INCOMPATIBLE_RELATION_GROUPS
                    and not explicit_transition
                ):
                    conflicts.append(
                        self._conflict(
                            fact,
                            conflict_type="relationship_conflict",
                            severity="major",
                            message=(
                                "Generated relationship contradicts current "
                                "Graph state."
                            ),
                            expected=relation.predicate,
                            generated=fact.predicate,
                            recommendation=(
                                "Preserve the current relationship or make the change "
                                "an explicit transition."
                            ),
                            entity_ids=[subject.entity_id, obj.entity_id],
                            evidence=[
                                ConsistencySource(
                                    source_type="temporal_relation",
                                    source_id=relation.relation_id,
                                    revision=relation.revision,
                                    excerpt=relation.description
                                    or relation.predicate,
                                )
                            ],
                        )
                    )
                    break

        if fact.fact_type == "life_state" and checks_world_state:
            candidate_state = self._life_state(fact.value)
            events = self.temporal_storage.list_events(
                novel_id,
                active_entity_ids=[subject.entity_id],
                as_of_chapter=chapter_number,
                include_historical=False,
                limit=self.CONSTRAINT_SCAN_LIMIT,
            )
            for event in events:
                if (
                    self._scope_from_metadata(event.metadata)
                    == "CHARACTER_BELIEF"
                ):
                    continue
                existing_state = self._event_life_state(event)
                if (
                    candidate_state
                    and existing_state
                    and candidate_state != existing_state
                    and not explicit_transition
                ):
                    conflicts.append(
                        self._conflict(
                            fact,
                            conflict_type="life_state_conflict",
                            severity="critical",
                            message=(
                                "Generated life state contradicts current "
                                "Graph state."
                            ),
                            expected=existing_state,
                            generated=candidate_state,
                            recommendation=(
                                "Preserve the current life state or explicitly "
                                "establish and review a state transition."
                            ),
                            entity_ids=[subject.entity_id],
                            evidence=[
                                ConsistencySource(
                                    source_type="temporal_event",
                                    source_id=event.event_id,
                                    revision=event.revision,
                                    excerpt=event.summary or event.title,
                                )
                            ],
                        )
                    )
                    break

        if fact.fact_type == "location" and obj is not None:
            if obj.entity_type != "location":
                conflicts.append(
                    self._conflict(
                        fact,
                        conflict_type="identity_mismatch",
                        severity="critical",
                        message="Location fact object is not a location entity.",
                        expected="location",
                        generated=obj.entity_type,
                        recommendation="Use a canonical location entity.",
                        entity_ids=[subject.entity_id, obj.entity_id],
                    )
                )
            if checks_world_state:
                events = self.temporal_storage.list_events(
                    novel_id,
                    active_entity_ids=[subject.entity_id],
                    as_of_chapter=chapter_number,
                    include_historical=False,
                    limit=self.CONSTRAINT_SCAN_LIMIT,
                )
                locations = [
                    event
                    for event in events
                    if self._scope_from_metadata(event.metadata)
                    != "CHARACTER_BELIEF"
                    and subject.entity_id in event.participant_entity_ids
                    and event.location_entity_id
                    and event.location_entity_id != obj.entity_id
                    and (
                        self._normalize(event.event_type)
                        in {"location", "located_at", "位置", "所在地"}
                        or event.metadata.get("state_type") == "location"
                    )
                ]
                if locations and not explicit_transition:
                    event = locations[0]
                    conflicts.append(
                        self._conflict(
                            fact,
                            conflict_type="location_conflict",
                            severity="major",
                            message=(
                                "Generated location contradicts current Graph state."
                            ),
                            expected=str(event.location_entity_id),
                            generated=obj.entity_id,
                            recommendation=(
                                "Keep the current location or show an explicit "
                                "movement."
                            ),
                            entity_ids=[
                                subject.entity_id,
                                str(event.location_entity_id),
                                obj.entity_id,
                            ],
                            evidence=[
                                ConsistencySource(
                                    source_type="temporal_event",
                                    source_id=event.event_id,
                                    revision=event.revision,
                                    excerpt=event.summary or event.title,
                                )
                            ],
                        )
                    )

        if fact.knowledge_scope == "CHARACTER_KNOWLEDGE":
            holder = fact.knowledge_holder_entity_id
            if not holder:
                conflicts.append(
                    self._conflict(
                        fact,
                        conflict_type="knowledge_scope_violation",
                        severity="major",
                        message="Character knowledge fact has no knowledge holder.",
                        expected="A canonical knowledge_holder_entity_id",
                        generated="missing",
                        recommendation="Identify the character who knows the fact.",
                        entity_ids=[subject.entity_id],
                    )
                )
            else:
                try:
                    holder_entity = self.novel_service.get_entity(
                        novel_id,
                        holder,
                    )
                except NovelProjectNotFoundError:
                    conflicts.append(
                        self._conflict(
                            fact,
                            conflict_type="unknown_entity",
                            severity="critical",
                            message=(
                                "Knowledge holder is not a canonical entity: "
                                f"{holder}"
                            ),
                            expected="A canonical character entity ID",
                            generated=holder,
                            recommendation=(
                                "Use an existing character as the knowledge holder."
                            ),
                            entity_ids=[subject.entity_id],
                        )
                    )
                    return conflicts
                if holder_entity.entity_type != "character":
                    conflicts.append(
                        self._conflict(
                            fact,
                            conflict_type="identity_mismatch",
                            severity="critical",
                            message="Knowledge holder is not a character entity.",
                            expected="character",
                            generated=holder_entity.entity_type,
                            recommendation=(
                                "Use a canonical character as knowledge holder."
                            ),
                            entity_ids=[subject.entity_id, holder],
                        )
                    )
                    return conflicts
            if holder and not explicit_transition:
                matching = [
                    item
                    for item in constraints
                    if subject.entity_id in item.entity_ids
                    and (obj is None or obj.entity_id in item.entity_ids)
                    and item.knowledge_scope != "CHARACTER_BELIEF"
                ]
                if not any(holder in item.knower_entity_ids for item in matching):
                    conflicts.append(
                        self._conflict(
                            fact,
                            conflict_type="knowledge_scope_violation",
                            severity="major",
                            status="confirmed",
                            message=(
                                "The character is shown as knowing a fact not present "
                                "in the character knowledge scope."
                            ),
                            expected=(
                                "Explicit character knowledge or an on-page "
                                "learning transition"
                            ),
                            generated=fact.evidence,
                            recommendation=(
                                "Remove the knowledge, mark it as belief, or show how "
                                "the character learns it."
                            ),
                            entity_ids=[subject.entity_id, holder],
                            evidence=[item.source for item in matching[:5]],
                        )
                    )
        return conflicts

    def check(
        self,
        novel_id: str,
        payload: ConsistencyCheckRequest,
    ) -> ConsistencyCheckResult:
        base = self.build_constraints(
            novel_id,
            ConsistencyConstraintRequest(
                user_id=payload.user_id,
                chapter_number=payload.chapter_number,
                active_entity_ids=payload.active_entity_ids,
                pov_character_id=payload.pov_character_id,
                char_budget=payload.char_budget,
            ),
        )
        facts = [item.model_copy(deep=True) for item in payload.candidate_facts]
        conflicts: list[ConsistencyConflict] = []
        for index, fact in enumerate(facts, start=1):
            fact.fact_id = self._fact_id(fact, index)
            if fact.chapter_number is None:
                fact.chapter_number = payload.chapter_number
            if self._normalize(fact.evidence) not in self._normalize(
                payload.content
            ):
                conflicts.append(
                    self._conflict(
                        fact,
                        conflict_type="unsupported_evidence",
                        severity="major",
                        message="Candidate fact evidence is not present in the text.",
                        expected="A verbatim excerpt from the supplied content",
                        generated=fact.evidence,
                        recommendation=(
                            "Remove the candidate fact or cite an exact excerpt."
                        ),
                        evidence=[self._source_for_generated(fact)],
                    )
                )
                continue
            conflicts.extend(
                self._check_fact(
                    novel_id,
                    payload.chapter_number,
                    base.constraints,
                    fact,
                )
            )
        conflicts.sort(key=lambda item: (item.candidate_fact_id, item.conflict_id))
        return ConsistencyCheckResult(
            novel_id=novel_id,
            chapter_number=payload.chapter_number,
            constraints=base.constraints,
            candidate_facts=facts,
            conflicts=conflicts,
            persisted=False,
            constraint_context=base.constraint_context,
        )

    @staticmethod
    def _extraction_instruction(content: str, chapter_number: int) -> str:
        return (
            "Extract only explicit factual assertions from the supplied novel "
            "text. Return exactly one JSON object without Markdown. Do not infer "
            "unstated facts. Names may be supplied when an entity ID is unknown. "
            "Use change_type=transition only when the text explicitly establishes "
            "a change or movement. CHARACTER_BELIEF may contradict world truth; "
            "CHARACTER_KNOWLEDGE means the character treats the fact as known.\n\n"
            "Schema: {\"candidate_facts\":[{\"fact_id\":\"FACT-001\","
            "\"fact_type\":\"relationship|life_state|location|identity|event\","
            "\"subject_entity_id\":null,\"subject_name\":null,"
            "\"predicate\":\"\",\"object_entity_id\":null,"
            "\"object_name\":null,\"value\":\"\","
            "\"evidence\":\"exact short excerpt\","
            f"\"chapter_number\":{chapter_number},"
            "\"change_type\":\"assertion|transition\",\"confidence\":1.0,"
            "\"knowledge_scope\":\"WORLD_TRUTH|CHARACTER_KNOWLEDGE|"
            "CHARACTER_BELIEF|READER_KNOWLEDGE\","
            "\"knowledge_holder_entity_id\":null}]}\n\n"
            "CHAPTER_BEGIN\n" + content + "\nCHAPTER_END"
        )

    async def analyze(
        self,
        novel_id: str,
        payload: ConsistencyAnalyzeRequest,
    ) -> ConsistencyAnalyzeResult:
        self._validate_scope(novel_id, payload.user_id)
        response = await self.llm_manager.chat(
            payload.provider,
            ChatRequest(
                provider=payload.provider,
                model=payload.model,
                messages=[
                    ChatMessage(
                        role="system",
                        content=(
                            "You are a conservative structured fact extractor. "
                            "Output JSON only and never invent facts."
                        ),
                    ),
                    ChatMessage(
                        role="user",
                        content=self._extraction_instruction(
                            payload.content,
                            payload.chapter_number,
                        ),
                    ),
                ],
                reasoning_effort=payload.reasoning_effort,
                temperature=payload.temperature,
                max_tokens=payload.max_tokens,
                metadata={
                    "user_id": payload.user_id,
                    "novel_id": novel_id,
                    "consistency_stage": "candidate_fact_extraction",
                },
            ),
        )
        if response.finish_reason == "length":
            raise ConsistencyOutputError("Consistency extraction was truncated.")
        try:
            extracted_payload = extract_json_object(response.content)
            candidate_facts = extracted_payload.get("candidate_facts")
            if isinstance(candidate_facts, list):
                for candidate in candidate_facts:
                    if isinstance(candidate, dict):
                        # The chapter is an authoritative request coordinate,
                        # not a value the extractor is allowed to choose.
                        candidate["chapter_number"] = payload.chapter_number
            extracted = _ExtractedFacts.model_validate(extracted_payload)
        except (PlannerOutputError, ValidationError) as exc:
            raise ConsistencyOutputError(
                "Consistency extraction output failed validation: " + str(exc)
            ) from exc
        checked = self.check(
            novel_id,
            ConsistencyCheckRequest(
                user_id=payload.user_id,
                chapter_number=payload.chapter_number,
                active_entity_ids=payload.active_entity_ids,
                pov_character_id=payload.pov_character_id,
                char_budget=payload.char_budget,
                content=payload.content,
                candidate_facts=extracted.candidate_facts,
            ),
        )
        return ConsistencyAnalyzeResult(
            **checked.model_dump(),
            provider=response.provider,
            model=response.model,
            finish_reason=response.finish_reason,
            usage=response.usage,
            latency_ms=response.latency_ms,
        )


consistency_engine = ConsistencyEngine()
