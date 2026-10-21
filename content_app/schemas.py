from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CHANNELS = ("linkedin", "newsletter", "website")


class Drafts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    linkedin: str = Field(min_length=1, max_length=5000)
    newsletter: str = Field(min_length=1, max_length=10000)
    website: str = Field(min_length=1, max_length=15000)


class ContentInput(BaseModel):
    source: str = Field(min_length=20, max_length=20000)


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


class RejectionInput(BaseModel):
    revision: int = Field(ge=1)
    justification: str = Field(min_length=10, max_length=2000)
