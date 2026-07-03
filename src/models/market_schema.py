from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, ConfigDict, Field


class SourceHealthSchema(BaseModel):
    status: str = Field(default="unavailable")
    count: int = Field(default=0)
    detail: str = Field(default="")


class SkillDetailSchema(BaseModel):
    source: str = Field(default="")
    confidence: float = Field(default=0.0)


class LifecycleEntrySchema(BaseModel):
    status: str = Field(default="stable")
    source: str = Field(default="")
    confidence: float = Field(default=0.0)
    google: Dict[str, float | str] = Field(default_factory=dict)


class MarketAgentOutputSchema(BaseModel):
    model_config = ConfigDict(extra="allow")  # Allow new fields

    market_gaps: List[str] = Field(default_factory=list)
    emerging_skills: List[str] = Field(default_factory=list)
    trending_skills: List[str] = Field(default_factory=list)
    vanishing_skills: List[str] = Field(default_factory=list)
    sources_used: List[str] = Field(default_factory=list)
    sources_attempted: List[str] = Field(default_factory=list)
    current_role: str = Field(default="")
    keywords_used: List[str] = Field(default_factory=list)
    source_trends: Dict[str, List[str]] = Field(default_factory=dict)
    skill_details: Dict[str, SkillDetailSchema] = Field(default_factory=dict)
    lifecycle: Dict[str, LifecycleEntrySchema] = Field(default_factory=dict)
    source_health: Dict[str, SourceHealthSchema] = Field(default_factory=dict)
    thought_process: List[str] = Field(default_factory=list)
    role_specific_trends: List[str] = Field(default_factory=list)
    industry_trending_skills: List[str] = Field(default_factory=list)
    skill_gaps: List[str] = Field(default_factory=list)
