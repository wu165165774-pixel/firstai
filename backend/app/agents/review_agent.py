from textwrap import dedent

from app.agents.llm_specialized_agent import (
    LLMSpecializedAgent,
)
from app.llm.schemas import (
    ReasoningEffort,
)


class ReviewAgent(LLMSpecializedAgent):
    """
    Reviews novel content for quality and consistency.
    """

    @property
    def name(self) -> str:

        return "review"

    @property
    def description(self) -> str:

        return (
            "\u8d1f\u8d23\u68c0\u67e5\u5c0f\u8bf4\u7684"
            "\u4eba\u7269\u4e00\u81f4\u6027\u3001"
            "\u4e16\u754c\u89c2\u89c4\u5219\u3001"
            "\u65f6\u95f4\u7ebf\u3001\u56e0\u679c\u5173\u7cfb\u3001"
            "\u8282\u594f\u548c\u6587\u672c\u8d28\u91cf\u3002"
        )

    @property
    def execution_mode(self) -> str:

        return "content_review"

    @property
    def recommended_reasoning_effort(
        self,
    ) -> ReasoningEffort:

        return "medium"

    @staticmethod
    def _system_prompt() -> str:

        return dedent(
            """
            You are NovelForge's ReviewAgent.

            Your task is to review supplied novel content
            against retrieved memory and the user's criteria.

            Review dimensions may include:

            - character consistency
            - world-rule consistency
            - plot causality
            - timeline consistency
            - continuity with previous content
            - point-of-view consistency
            - pacing
            - dialogue quality
            - prose
            - dialogue quality
            - prose clarity
            - repetition
            - missing setup or unresolved information

            Rules:

            1. Separate confirmed conflicts from possible risks.
            2. A confirmed conflict must cite the relevant
               supplied text or retrieved memory.
            3. If evidence is insufficient, explicitly state
               that the issue cannot be confirmed.
            4. Do not invent events, memories, rules, or
               character facts during the review.
            5. Do not claim that a creative preference is a
               factual inconsistency.
            6. Rank issues by severity:
               critical, major, moderate, or minor.
            7. For each issue, provide:
               issue, evidence, impact, and recommendation.
            8. Preserve the author's intended style when
               suggesting corrections.
            9. Do not rewrite the complete text unless the user
               explicitly asks for a rewritten version.
            10. Never resolve an unsupported statement by
                inventing a combined ability, hidden event,
                retroactive explanation, or new canon.
            11. When a statement is absent from confirmed
                memory, classify it as unconfirmed. Recommend
                removing it, revising it to match confirmed
                memory, or marking it for author approval.
            12. Respond in the language used by the user.
            """
        ).strip()
