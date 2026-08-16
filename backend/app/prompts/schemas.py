from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PromptCategory = Literal["agent", "consistency", "memory"]


class PromptDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_id: str = Field(min_length=1, max_length=128)
    category: PromptCategory
    description: str = Field(min_length=1, max_length=512)
    current_revision: int = Field(ge=1)
    available_revisions: list[int] = Field(min_length=1, max_length=100)


class PromptProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=1)
    rendered_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rendered_chars: int = Field(ge=0)


class PromptCatalogData(BaseModel):
    prompts: list[PromptDescriptor] = Field(default_factory=list)


class PromptCatalogResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: PromptCatalogData
