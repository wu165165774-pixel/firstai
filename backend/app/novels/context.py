from __future__ import annotations

import json

from typing import Any

from .schemas import NovelEntity
from .service import NovelProjectService
from .storage import NovelProjectNotFoundError


class CanonContextBuilder:
    """Builds a bounded P0 Canon block for LLM agents."""

    CONTEXT_CHAR_BUDGET = 3600
    ENTITY_LIMIT = 32
    _CHARACTER_CANON_KEYS = (
        "gender",
        "role",
        "identity",
        "background",
        "description",
        "relationships",
        "abilities",
        "faction",
    )

    def __init__(
        self,
        service: NovelProjectService | None = None,
    ) -> None:
        self.service = service or NovelProjectService()

    @staticmethod
    def _compact(
        value: Any,
        *,
        text_limit: int,
        list_limit: int,
        dict_limit: int,
    ) -> Any:
        if isinstance(value, str):
            if len(value) <= text_limit:
                return value
            return value[:text_limit].rstrip() + "…"
        if isinstance(value, list):
            return [
                CanonContextBuilder._compact(
                    item,
                    text_limit=text_limit,
                    list_limit=list_limit,
                    dict_limit=dict_limit,
                )
                for item in value[:list_limit]
            ]
        if isinstance(value, dict):
            return {
                str(key): CanonContextBuilder._compact(
                    item,
                    text_limit=text_limit,
                    list_limit=list_limit,
                    dict_limit=dict_limit,
                )
                for key, item in list(value.items())[:dict_limit]
            }
        return value

    @staticmethod
    def _entity_item(
        entity: NovelEntity,
        story_bible_character: dict[str, Any] | None,
    ) -> dict[str, Any]:
        item: dict[str, Any] = {
            "entity_id": entity.entity_id,
            "entity_type": entity.entity_type,
            "canonical_name": entity.canonical_name,
            "aliases": entity.aliases,
        }
        if entity.description:
            item["description"] = entity.description

        if story_bible_character:
            facts = {
                key: story_bible_character[key]
                for key in CanonContextBuilder._CHARACTER_CANON_KEYS
                if key in story_bible_character
                and story_bible_character[key] not in (None, "", [], {})
            }
            if facts:
                item["canon_profile"] = facts
        return item

    @staticmethod
    def _active_ids(
        values: list[str] | None,
    ) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values or []:
            entity_id = str(value or "").strip()
            if not entity_id or entity_id in seen:
                continue
            seen.add(entity_id)
            result.append(entity_id)
        return result

    def _load_entities(
        self,
        novel_id: str,
        active_entity_ids: list[str],
    ) -> tuple[list[NovelEntity], list[str]]:
        if not active_entity_ids:
            return (
                self.service.list_entities(
                    novel_id,
                    limit=self.ENTITY_LIMIT,
                ),
                [],
            )

        entities: list[NovelEntity] = []
        unresolved: list[str] = []
        for entity_id in active_entity_ids[: self.ENTITY_LIMIT]:
            try:
                entities.append(
                    self.service.get_entity(
                        novel_id,
                        entity_id,
                    )
                )
            except NovelProjectNotFoundError:
                unresolved.append(entity_id)
        return entities, unresolved

    @classmethod
    def _render(cls, payload: dict[str, Any]) -> str:
        prefix = (
            "[CANON FACTS - MUST NOT VIOLATE]\n"
            "This is P0 authoritative novel identity and hard-setting context.\n"
            "Canonical entity_id determines identity; names are display values.\n"
            "Lower-priority Memory/RAG evidence must not override this block.\n"
            "Do not treat world truth as POV knowledge unless explicitly supplied.\n"
        )
        passes = (
            (480, 16, 20),
            (320, 12, 16),
            (220, 8, 12),
            (140, 6, 10),
            (96, 4, 8),
        )

        for text_limit, list_limit, dict_limit in passes:
            compacted = cls._compact(
                payload,
                text_limit=text_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
            )
            rendered = prefix + json.dumps(
                compacted,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if len(rendered) <= cls.CONTEXT_CHAR_BUDGET:
                return rendered

        minimal = {
            "priority": "P0_CANON",
            "source_revisions": payload.get("source_revisions", {}),
            "entities": [],
            "unresolved_entity_ids": payload.get(
                "unresolved_entity_ids",
                [],
            )[:4],
        }
        for entity in payload.get("entities", []):
            candidate = {
                "entity_id": entity.get("entity_id", ""),
                "entity_type": entity.get("entity_type", ""),
                "canonical_name": entity.get("canonical_name", "")[:96],
                "aliases": entity.get("aliases", [])[:3],
            }
            minimal["entities"].append(candidate)
            rendered = prefix + json.dumps(
                minimal,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if len(rendered) > cls.CONTEXT_CHAR_BUDGET:
                minimal["entities"].pop()
                break

        return prefix + json.dumps(
            minimal,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    async def build(
        self,
        novel_id: str,
        *,
        active_entity_ids: list[str] | None = None,
    ) -> str:
        novel_id = str(novel_id or "").strip()
        if not novel_id:
            return ""

        try:
            project = self.service.get_project(novel_id)
            bible = self.service.get_story_bible(novel_id)
            active_ids = self._active_ids(active_entity_ids)
            entities, unresolved = self._load_entities(
                novel_id,
                active_ids,
            )
        except NovelProjectNotFoundError:
            return ""

        bible_characters = {
            str(character.get("entity_id")): character
            for character in bible.characters
            if isinstance(character, dict)
            and character.get("entity_id")
        }
        payload = {
            "priority": "P0_CANON",
            "source_revisions": {
                "project_revision": project.revision,
                "story_bible_revision": bible.revision,
            },
            "hard_constraints": project.constraints,
            "style_guide": project.style_guide,
            "world": bible.world,
            "rules": bible.rules,
            "themes": bible.themes,
            "entities": [
                self._entity_item(
                    entity,
                    bible_characters.get(entity.entity_id),
                )
                for entity in entities
            ],
            "unresolved_entity_ids": unresolved,
        }

        if not any(
            payload[key]
            for key in (
                "hard_constraints",
                "style_guide",
                "world",
                "rules",
                "themes",
                "entities",
                "unresolved_entity_ids",
            )
        ):
            return ""
        return self._render(payload)


canon_context_builder = CanonContextBuilder()
