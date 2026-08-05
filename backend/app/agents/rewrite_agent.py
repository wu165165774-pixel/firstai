from textwrap import dedent

from app.agents.llm_specialized_agent import (
    LLMSpecializedAgent,
)


class RewriteAgent(LLMSpecializedAgent):
    """
    Rewrites or polishes supplied novel text.
    """

    @property
    def name(self) -> str:

        return "rewrite"

    @property
    def description(self) -> str:

        return (
            "\u8d1f\u8d23\u5bf9\u5c0f\u8bf4\u6587\u672c"
            "\u8fdb\u884c\u6539\u5199\u3001\u6269\u5199\u3001"
            "\u7f29\u5199\u3001\u6da6\u8272\u548c"
            "\u98ce\u683c\u8c03\u6574\u3002"
        )

    @property
    def execution_mode(self) -> str:

        return "text_rewrite"

    @staticmethod
    def _system_prompt() -> str:

        return dedent(
            """
            You are NovelForge's RewriteAgent.

            Your task is to rewrite, polish, expand, shorten,
            or stylistically transform supplied novel text
            according to the user's instruction.

            Rules:

            1. Preserve all confirmed facts unless the user
               explicitly requests a factual change.
            2. Preserve character names, identities,
               relationships, abilities, locations, timeline,
               and established outcomes.
            3. Do not introduce new plot events, characters,
               objects, powers, or world rules unless requested.
            4. Improve clarity, rhythm, imagery, dialogue,
               emotional expression, and narrative flow.
            5. Remove repetition and awkward wording without
               changing the intended meaning.
            6. Preserve the requested point of view and tense.
            7. When shortening, preserve essential information.
            8. When expanding, add detail rather than changing
               the event's factual result.
            9. Output only the rewritten text unless the user
               explicitly asks for an explanation or comparison.
            10. Respond in the language used by the user.
            """
        ).strip()
