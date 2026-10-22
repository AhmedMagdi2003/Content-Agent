from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CHANNELS = ("linkedin", "newsletter", "website")


class Drafts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    linkedin: str = Field(min_length=1, max_length=5000)
    newsletter: str = Field(min_length=1, max_length=10000)
    website: str = Field(min_length=1, max_length=15000)


class Citation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    block_id: str = Field(default="C1", description="Identifier for the citation block, e.g. C1")
    channel: Literal["linkedin", "newsletter", "website", "all"] = Field(
        default="all", description="Channel where this claim is made"
    )
    claim: str = Field(description="Statement or claim in the generated draft")
    source_type: Literal["source_brief", "past_post", "scraped_link", "web_search"] = Field(
        default="source_brief", description="Category of the source"
    )
    source_title: str = Field(default="Source Brief", description="Title or name of the source")
    source_url: str | None = Field(default=None, description="URL of the source if web or link")
    source_quote: str = Field(default="", description="Exact supporting snippet from source facts")


class GenerationResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    linkedin: str = Field(min_length=1, max_length=5000)
    newsletter: str = Field(min_length=1, max_length=10000)
    website: str = Field(min_length=1, max_length=15000)
    citations: list[Citation] = Field(default_factory=list)
    new_achievements: list[str] = Field(
        default_factory=list,
        description="Specific milestones/achievements completed in this update",
    )


class ContentInput(BaseModel):
    source: str = Field(min_length=20, max_length=20000)
    project_label: str | None = Field(default=None, max_length=200)
    project_slug: str | None = Field(default=None, max_length=100)
    content_type: Literal["project_description", "project_update", "research_finding", "event"] = (
        "project_update"
    )
    enable_web_search: bool = Field(default=False)
    search_query: str | None = Field(default=None, max_length=500)
    given_links: list[str] = Field(default_factory=list)


class RevisionInput(BaseModel):
    revision: int = Field(ge=1)
    drafts: Drafts
    channels: list[Literal["linkedin", "newsletter", "website"]] = Field(min_length=1)

    @field_validator("channels")
    @classmethod
    def unique_channels(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Duplicate channel selection")
        return sorted(value)


class ApprovalInput(BaseModel):
    revision: int = Field(ge=1)
    digest: str = Field(min_length=64, max_length=64)


class GenerateInput(BaseModel):
    revision: int = Field(ge=1)


class RejectionInput(BaseModel):
    revision: int = Field(ge=1)
    justification: str = Field(min_length=10, max_length=2000)
