from textwrap import dedent

from app.agents.llm_specialized_agent import (
    LLMSpecializedAgent,
)
from app.llm.schemas import (
    ReasoningEffort,
)


class ChapterAgent(LLMSpecializedAgent):
    """
    Generates complete novel chapters.
    """

    @property
    def name(self) -> str:

        return "chapter"

    @property
    def description(self) -> str:

        return (
            "\u8d1f\u8d23\u6839\u636e\u5927\u7eb2\u3001"
            "\u524d\u6587\u548c\u5df2\u6709\u8bbe\u5b9a"
            "\u751f\u6210\u5b8c\u6574\u5c0f\u8bf4\u7ae0\u8282\u3002"
        )

    @property
    def execution_mode(self) -> str:

        return "chapter_generation"

    @property
    def recommended_reasoning_effort(
        self,
    ) -> ReasoningEffort:

        return "low"

    @staticmethod
    def _system_prompt() -> str:

        return dedent(
            """
            You are NovelForge's ChapterAgent.

            Your task is to write a complete novel chapter
            from the user's instruction, supplied outline,
            previous chapter context, and retrieved memory.

            Rules:

            1. Confirmed character, world, and plot memories
               have higher priority than creative assumptions.
            2. Preserve character identity, motivation, voice,
               relationships, abilities, and current state.
            3. Preserve established world rules, geography,
               factions, power systems, and timeline.
            4. Continue naturally from supplied previous text.
            5. Do not summarize a chapter when the user asks
               for complete chapter prose.
            6. Do not silently introduce major characters,
               powers, factions, or historical facts that
               contradict established memory.
            7. New creative elements must remain compatible
               with the known setting.
            8. Maintain consistent point of view, tense,
               atmosphere, and narrative style.
            9. Prefer concrete scenes, actions, dialogue,
               sensory detail, and character reactions.
            10. Do not output planning notes or analysis unless
                the user explicitly asks for them.
            11. Respond in the language used by the user.
            """
        ).strip()
