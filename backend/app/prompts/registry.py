from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.llm.schemas import ChatMessage
from app.prompts.schemas import (
    PromptCategory,
    PromptDescriptor,
    PromptProvenance,
)


class PromptNotFoundError(LookupError):
    pass


class PromptRevisionNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class PromptRevision:
    prompt_id: str
    revision: int
    category: PromptCategory
    description: str


class PromptRegistry:
    def __init__(self) -> None:
        self._revisions: dict[str, dict[int, PromptRevision]] = {}
        self._current: dict[str, int] = {}

    def register(
        self,
        *,
        prompt_id: str,
        revision: int,
        category: PromptCategory,
        description: str,
        current: bool = True,
    ) -> None:
        prompt_id = prompt_id.strip()
        description = description.strip()
        if not prompt_id or not description:
            raise ValueError("Prompt ID and description must not be blank.")
        if revision < 1:
            raise ValueError("Prompt revision must be positive.")
        revisions = self._revisions.setdefault(prompt_id, {})
        if revision in revisions:
            raise ValueError(
                f"Prompt revision already registered: {prompt_id}@{revision}"
            )
        revisions[revision] = PromptRevision(
            prompt_id=prompt_id,
            revision=revision,
            category=category,
            description=description,
        )
        if current or prompt_id not in self._current:
            self._current[prompt_id] = revision

    def select(
        self,
        prompt_id: str,
        revision: int | None = None,
    ) -> PromptRevision:
        try:
            revisions = self._revisions[prompt_id]
        except KeyError as exc:
            raise PromptNotFoundError(
                f"Prompt not found: {prompt_id}"
            ) from exc
        selected = revision if revision is not None else self._current[prompt_id]
        try:
            return revisions[selected]
        except KeyError as exc:
            raise PromptRevisionNotFoundError(
                f"Prompt revision not found: {prompt_id}@{selected}"
            ) from exc

    def list(self) -> list[PromptDescriptor]:
        return [
            PromptDescriptor(
                prompt_id=prompt_id,
                category=self.select(prompt_id).category,
                description=self.select(prompt_id).description,
                current_revision=self._current[prompt_id],
                available_revisions=sorted(revisions),
            )
            for prompt_id, revisions in sorted(self._revisions.items())
        ]

    def provenance(
        self,
        prompt_id: str,
        rendered: str,
        *,
        revision: int | None = None,
    ) -> PromptProvenance:
        selected = self.select(prompt_id, revision)
        return PromptProvenance(
            prompt_id=selected.prompt_id,
            revision=selected.revision,
            rendered_sha256=hashlib.sha256(
                rendered.encode("utf-8")
            ).hexdigest(),
            rendered_chars=len(rendered),
        )

    def request_provenance(
        self,
        prompt_id: str,
        messages: list[ChatMessage],
        *,
        revision: int | None = None,
    ) -> PromptProvenance:
        rendered = json.dumps(
            [
                {
                    "role": message.role,
                    "content": message.content,
                }
                for message in messages
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return self.provenance(
            prompt_id,
            rendered,
            revision=revision,
        )
