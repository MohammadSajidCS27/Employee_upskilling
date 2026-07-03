from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, ConfigDict, Field


class UserProfileSchema(BaseModel):
    employee_id: str = Field(default="EMP001")
    name: str = Field(default="Unknown")
    current_role: str = Field(default="Unknown")
    experience_years: int = Field(default=0)


class ReadinessSummarySchema(BaseModel):
    readiness_score: float = Field(default=0.0)
    readiness_category: str = Field(default="early_stage")
    readiness_message: str = Field(default="Good starting point, structured plan needed")
    total_skills_required: int = Field(default=0)
    skills_completed: int = Field(default=0)
    skills_partial: int = Field(default=0)
    skills_missing: int = Field(default=0)


class SkillGapItemSchema(BaseModel):
    skill: str
    user_level: int = Field(default=0)
    required_level: int = Field(default=0)
    gap: int = Field(default=0)
    priority: str = Field(default="medium")
    importance: str = Field(default="core")
    category: str = Field(default="general")
    evidence: str | None = None
    status: str = Field(default="missing")


class PrioritySkillItemSchema(BaseModel):
    skill: str
    priority_rank: int = Field(default=1)
    priority: str = Field(default="medium")
    gap: int = Field(default=0)
    category: str = Field(default="general")


class SkillAnalysisSchema(BaseModel):
    matched_skills: List[str] = Field(default_factory=list)
    skill_gaps: List[SkillGapItemSchema] = Field(default_factory=list)
    missing_core_skills: List[SkillGapItemSchema] = Field(default_factory=list)
    missing_optional_skills: List[SkillGapItemSchema] = Field(default_factory=list)
    priority_skills: List[PrioritySkillItemSchema] = Field(default_factory=list)


class SkillDependencySchema(BaseModel):
    requires: List[str] = Field(default_factory=list)
    dependency_met: bool = Field(default=False)
    missing_dependencies: List[str] = Field(default_factory=list)
    dependency_score: float = Field(default=0.0)


class RecommendationsSchema(BaseModel):
    immediate_actions: List[str] = Field(default_factory=list)
    short_term_goals: List[str] = Field(default_factory=list)
    long_term_goals: List[str] = Field(default_factory=list)


class SkillSourceSchema(BaseModel):
    provider: str = Field(default="unknown")
    source: str = Field(default="unknown")
    live: bool = Field(default=False)
    workbook_file: str = Field(default="")
    sheet: str = Field(default="")


class SkillGapResponseSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_profile: UserProfileSchema
    readiness_summary: ReadinessSummarySchema
    skill_analysis: SkillAnalysisSchema
    skill_dependencies: Dict[str, SkillDependencySchema] = Field(default_factory=dict)
    core_gaps: List[str] = Field(default_factory=list)
    core_gaps_by_heading: Dict[str, List[str]] = Field(default_factory=dict)
    skill_source: SkillSourceSchema = Field(default_factory=SkillSourceSchema)
    recommendations: RecommendationsSchema
