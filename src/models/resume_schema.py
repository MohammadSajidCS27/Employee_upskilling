from __future__ import annotations

from typing import List

from pydantic import BaseModel, ConfigDict, Field


class UserProfileSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default="")
    name: str = Field(default="")
    email: str = Field(default="")
    siemens_id: str = Field(default="")
    department: str = Field(default="")
    role: str = Field(default="Software Developer")
    experience_years: int = Field(default=0)
    skills: List[str] = Field(default_factory=list)
    education: List[str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    target_roles: List[str] = Field(default_factory=list)
    created_at: str = Field(default="")
    updated_at: str = Field(default="")


class ResumeProfileSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(default="Software Developer")
    experience: int = Field(default=0)
    skills: List[str] = Field(default_factory=list)
    education: List[str] = Field(default_factory=list)
