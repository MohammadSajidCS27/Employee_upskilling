from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field


class CareerInputProfileSchema(BaseModel):
    current_role: str = Field(default="Unknown")
    target_role: str = Field(default="Unknown Role")
    experience_years: int = Field(default=0)


class CareerSkillGapContextSchema(BaseModel):
    source_agent: str = Field(default="skill_agent")
    current_skills: List[str] = Field(default_factory=list)
    readiness_summary: Dict[str, Any] = Field(default_factory=dict)
    core_gaps: List[str] = Field(default_factory=list)
    skill_analysis: Dict[str, Any] = Field(default_factory=dict)


class CareerFeasibilitySchema(BaseModel):
    transition_score: float = Field(default=0.0)
    current_role: str = Field(default="Unknown")
    target_role: str = Field(default="Unknown Role")
    matched_skills_count: int = Field(default=0)
    skills_to_develop: int = Field(default=0)
    critical_gaps: List[str] = Field(default_factory=list)
    feasibility: str = Field(default="Low")


class CareerPathOptionsSchema(BaseModel):
    current_role: str = Field(default="Unknown")
    possible_transitions: List[str] = Field(default_factory=list)
    skill_aligned_roles_count: int = Field(default=0)


class CareerTimelineSchema(BaseModel):
    skill_gaps: int = Field(default=0)
    estimated_weeks: int = Field(default=0)
    estimated_months: float = Field(default=0.0)
    timeline_phases: Dict[str, str] = Field(default_factory=dict)
    experience_adjustment: str = Field(default="100%")


class CareerRecommendationSchema(BaseModel):
    recommendation: str = Field(default="")
    priority: str = Field(default="")
    alternatives: List[str] = Field(default_factory=list)


class CareerAgentOutputSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_profile: CareerInputProfileSchema
    skill_gap_context: CareerSkillGapContextSchema
    feasibility_analysis: CareerFeasibilitySchema
    career_path_options: CareerPathOptionsSchema
    transition_timeline: CareerTimelineSchema
    recommendation: CareerRecommendationSchema
    thought_process: List[str] = Field(default_factory=list)
