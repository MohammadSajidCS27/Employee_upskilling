"""Talent Matching Agent using LangGraph and LangChain patterns."""
import logging
from typing import Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from src.tools.talent_tools import TalentTools

logger = logging.getLogger(__name__)


class TalentAgentState(TypedDict):
    job_description: str
    employee_repo: List[Dict]
    required_skills: List[str]
    matches: List[Dict]
    messages: List[BaseMessage]
    current_step: str
    error: Optional[str]


class TalentAgent:
    """LangGraph talent matching agent."""

    def __init__(
        self,
        employee_repo: Optional[List[Dict]] = None,
        llm_client=None,
        skill_catalog: Optional[List[str]] = None,
        max_matches: int = 5,
    ):
        self.employee_repo = employee_repo or []
        self.max_matches = max(1, max_matches)
        self.tools = TalentTools(llm_client=llm_client, skill_catalog=skill_catalog)
        self.graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(TalentAgentState)
        graph.add_node("think", self._think_node)
        graph.add_node("extract_skills", self._extract_skills_node)
        graph.add_node("rank", self._rank_node)
        graph.add_node("finalize", self._finalize_node)

        graph.set_entry_point("think")
        graph.add_edge("think", "extract_skills")
        graph.add_edge("extract_skills", "rank")
        graph.add_edge("rank", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    def _think_node(self, state: TalentAgentState) -> dict:
        state["messages"].append(AIMessage(content="[THINK] Determine skills needed for ranking candidates"))
        state["current_step"] = "think"
        return state

    def _extract_skills_node(self, state: TalentAgentState) -> dict:
        state["required_skills"] = self.tools.extract_required_skills(state["job_description"])
        state["messages"].append(
            AIMessage(content=f"[ACT] Extracted {len(state['required_skills'])} required skills")
        )
        state["current_step"] = "extract_skills"
        return state

    def _rank_node(self, state: TalentAgentState) -> dict:
        state["matches"] = self.tools.rank_employees(
            state["employee_repo"],
            state["required_skills"],
            self.max_matches,
        )
        state["messages"].append(AIMessage(content=f"[ACT] Ranked {len(state['matches'])} candidates"))
        state["current_step"] = "rank"
        return state

    def _finalize_node(self, state: TalentAgentState) -> dict:
        state["messages"].append(AIMessage(content="[SUMMARY] Talent matching complete"))
        state["current_step"] = "complete"
        return state

    def match_employees(self, job_description: str) -> List[Dict]:
        initial_state = TalentAgentState(
            job_description=job_description,
            employee_repo=self.employee_repo,
            required_skills=[],
            matches=[],
            messages=[HumanMessage(content="Match candidates for job description")],
            current_step="",
            error=None,
        )

        result = self.graph.invoke(initial_state)
        return result["matches"]
