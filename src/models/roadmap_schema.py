"""Pydantic schema for the roadmap.sh-style learning roadmap output."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class RoadmapNodeSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    node_id: str
    label: str = Field(default="")
    type: str = Field(default="subtopic")
    phase_id: str = Field(default="")
    category: str = Field(default="")
    skill_key: str = Field(default="")
    depends_on: List[str] = Field(default_factory=list)
    status: str = Field(default="locked")
    importance: str = Field(default="important")
    resources: List[Any] = Field(default_factory=list)
    matched_skill: str = Field(default="")
    source_roadmap: str = Field(default="")
    original_node_id: str = Field(default="")
    skill_status: str = Field(default="locked")
    skill_priority: str = Field(default="")
    skill_importance: str = Field(default="")


class RoadmapPhaseSchema(BaseModel):
    phase_id: str
    phase_title: str = Field(default="Phase")
    phase_order: int = Field(default=1)
    skill: str = Field(default="")
    source: str = Field(default="standard_roadmap")
    nodes: List[RoadmapNodeSchema] = Field(default_factory=list)


class RoadmapEdgeSchema(BaseModel):
    source: str
    target: str
    type: str = Field(default="optional")


class RoadmapMetadataSchema(BaseModel):
    employee_id: Optional[str] = None
    name: Optional[str] = None
    current_role: Optional[str] = None
    target_role: Optional[str] = None
    experience_years: Optional[int] = None
    readiness_score: Optional[float] = None
    readiness_category: Optional[str] = None
    readiness_message: Optional[str] = None
    total_phases: int = Field(default=0)
    total_nodes: int = Field(default=0)
    total_edges: int = Field(default=0)
    source_roadmaps: List[str] = Field(default_factory=list)
    uncovered_skills: List[str] = Field(default_factory=list)
    agent_issues: List[Dict[str, str]] = Field(default_factory=list)


class LearningPhaseDetailSchema(BaseModel):
    skills: List[str] = Field(default_factory=list)
    duration_weeks: int = Field(default=0)
    description: str = Field(default="")


class LearningPathSchema(BaseModel):
    total_gaps: int = Field(default=0)
    phases: Dict[str, LearningPhaseDetailSchema] = Field(default_factory=dict)
    total_estimated_weeks: int = Field(default=0)


class RoadmapOutputSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    roadmap_id: str = Field(default="roadmap-agent")
    roadmap_title: str = Field(default="Learning Roadmap")
    version: str = Field(default="1.0.0")
    generated_with: str = Field(default="langgraph-learning-agent")
    generated_at: str = Field(default="")
    metadata: RoadmapMetadataSchema = Field(default_factory=RoadmapMetadataSchema)
    phases: List[RoadmapPhaseSchema] = Field(default_factory=list)
    edges: List[RoadmapEdgeSchema] = Field(default_factory=list)
    skill_gaps: List[str] = Field(default_factory=list)
    learning_path: LearningPathSchema = Field(default_factory=LearningPathSchema)
    project_roadmap: Dict[str, Any] = Field(default_factory=dict)
    learning_resources: Dict[str, Any] = Field(default_factory=dict)
    thought_process: List[str] = Field(default_factory=list)
