from textwrap import dedent

from app.agents.llm_specialized_agent import (
    LLMSpecializedAgent,
)
from app.llm.schemas import ReasoningEffort


class PlannerAgent(LLMSpecializedAgent):
    """Generates structured planning candidates."""

    @property
    def name(self) -> str:
        return "planner"

    @property
    def description(self) -> str:
        return (
            "Generates validated Novel Plan, Story Arc, and "
            "Chapter Plan candidates from authoritative novel context."
        )

    @property
    def execution_mode(self) -> str:
        return "structured_planning"

    @property
    def recommended_reasoning_effort(
        self,
    ) -> ReasoningEffort:
        return "medium"

    @staticmethod
    def _system_prompt() -> str:
        return dedent(
            """
            You are NovelForge's PlannerAgent.

            Your job is to produce structured planning candidates,
            not prose chapters and not database mutations.

            Rules:
            1. Treat the supplied Novel Project, Story Bible,
               Novel Plan, Story Arcs, and Chapter Plans as the
               authoritative current context.
            2. Do not contradict confirmed names, world rules,
               timeline facts, character identities, or established
               planning decisions unless the user's instruction
               explicitly requests a change.
            3. Respect all fixed identifiers and coordinates supplied
               by the request, including volume_number, arc_number,
               arc_id, and chapter_number.
            4. Produce exactly one JSON object matching the supplied
               JSON schema. Do not wrap it in Markdown.
            5. Do not include commentary, analysis, XML, YAML, or
               explanatory text outside the JSON object.
            6. Do not include database revision fields,
               expected_revision, is_stale, created_at, or updated_at
               inside the candidate unless the schema explicitly
               requests them.
            7. Prefer coherent causality, clear objectives, concrete
               conflicts, useful turning points, and actionable scene
               beats over vague planning language.
            8. Respond in the language requested by the author and
               preserve the language of established novel content.
            """
        ).strip()
