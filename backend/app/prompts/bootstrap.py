from app.prompts.registry import PromptRegistry


prompt_registry = PromptRegistry()


def _register_agent(name: str, description: str) -> None:
    prompt_registry.register(
        prompt_id=f"agent.{name}.system",
        revision=1,
        category="agent",
        description=f"{description} system instruction.",
    )
    prompt_registry.register(
        prompt_id=f"agent.{name}.request",
        revision=1,
        category="agent",
        description=f"{description} fully assembled chat request.",
    )


for _name, _description in (
    ("novel", "General novel agent"),
    ("character", "Character agent"),
    ("world", "World-building agent"),
    ("plot", "Plot agent"),
    ("chapter", "Chapter drafting agent"),
    ("review", "Chapter review agent"),
    ("rewrite", "Chapter rewrite agent"),
    ("planner", "Structured planner agent"),
):
    _register_agent(_name, _description)


for _prompt_id, _category, _description in (
    (
        "consistency.fact_extraction.system",
        "consistency",
        "Consistency candidate-fact extractor system instruction.",
    ),
    (
        "consistency.fact_extraction.request",
        "consistency",
        "Consistency candidate-fact extractor assembled request.",
    ),
    (
        "memory.extraction.system",
        "memory",
        "Long-term memory extractor system instruction.",
    ),
    (
        "memory.extraction.request",
        "memory",
        "Long-term memory extractor assembled request.",
    ),
):
    prompt_registry.register(
        prompt_id=_prompt_id,
        revision=1,
        category=_category,
        description=_description,
    )
