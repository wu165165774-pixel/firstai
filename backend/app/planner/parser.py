from __future__ import annotations

import json

from pydantic import ValidationError

from .schemas import (
    ChapterPlanCandidate,
    NovelPlanCandidate,
    PlannerCandidate,
    PlannerTarget,
    StoryArcCandidate,
)


class PlannerOutputError(ValueError):
    pass


_CANDIDATE_MODELS = {
    "novel_plan": NovelPlanCandidate,
    "story_arc": StoryArcCandidate,
    "chapter_plan": ChapterPlanCandidate,
}


def candidate_model(target: PlannerTarget):
    return _CANDIDATE_MODELS[target]


def extract_json_object(content: str) -> dict:
    text = (content or "").strip()

    if not text:
        raise PlannerOutputError("Planner returned empty content.")

    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start = text.find("{")
    end = text.rfind("}")

    if start < 0 or end < start:
        raise PlannerOutputError(
            "Planner output does not contain a JSON object."
        )

    raw = text[start : end + 1]

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PlannerOutputError(
            f"Planner output is not valid JSON: {exc.msg}"
        ) from exc

    if not isinstance(value, dict):
        raise PlannerOutputError(
            "Planner JSON root must be an object."
        )

    return value


def parse_candidate(
    target: PlannerTarget,
    content: str,
) -> PlannerCandidate:
    payload = extract_json_object(content)
    model = candidate_model(target)

    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise PlannerOutputError(
            "Planner JSON failed candidate validation: "
            + str(exc)
        ) from exc
