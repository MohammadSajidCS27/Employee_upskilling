"""Market Intelligence Agent using LangGraph and LangChain patterns."""
import logging
import time
from difflib import SequenceMatcher
from typing import Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from src.tools.market_tools import MarketTools
from src.models.market_schema import MarketAgentOutputSchema
from src.services.dynamic_defaults import default_role_trending_skills

logger = logging.getLogger(__name__)


class MarketAgentState(TypedDict):
    profile: Dict
    current_skills: List[str]
    emerging_skill_details: Dict
    lifecycle: Dict
    industry_trending_skills: List[str]
    market_gaps: List[str]
    trending_skills: List[str]
    vanishing_skills: List[str]
    emerging_skills: List[str]
    role_specific_trends: List[str]
    messages: List[BaseMessage]
    current_step: str
    error: Optional[str]
    start_time: float


class MarketAgent:
    """LangGraph market intelligence agent."""

    def __init__(
        self,
        esco_repo=None,
        onet_repo=None,
        google_trends=None,
        github_trends=None,
        youtube_signals=None,
        job_market_signals=None,
        llm_client=None,
        tech_keywords: Optional[List[str]] = None,
        max_market_gaps: int = 5,
        max_emerging_skills: int = 10,
    ):
        self.llm = llm_client
        self.max_market_gaps = max(1, max_market_gaps)
        self.max_emerging_skills = max(1, max_emerging_skills)
        self.overall_timeout_seconds = 12
        self.tools = MarketTools(
            esco_repo=esco_repo,
            onet_repo=onet_repo,
            google_trends=google_trends,
            github_trends=github_trends,
            youtube_signals=youtube_signals,
            job_market_signals=job_market_signals,
            tech_keywords=tech_keywords or [],
        )
        self.graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(MarketAgentState)
        graph.add_node("think", self._think_node)
        graph.add_node("collect", self._collect_node)
        graph.add_node("classify", self._classify_node)
        graph.add_node("compute_gaps", self._compute_gaps_node)
        graph.add_node("finalize", self._finalize_node)

        graph.set_entry_point("think")
        graph.add_edge("think", "collect")
        graph.add_edge("collect", "classify")
        graph.add_edge("classify", "compute_gaps")
        graph.add_edge("compute_gaps", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    @staticmethod
    def _tokenize(value: str) -> List[str]:
        normalized = " ".join(str(value or "").lower().split())
        tokens = [token.strip(".,:/()[]{}") for token in normalized.split()]
        return [token for token in tokens if token]

    @staticmethod
    def _normalize_keyword(value: str) -> str:
        return " ".join(str(value or "").strip().lower().split())

    def _build_market_keywords(self, profile: Dict, current_skills: List[str]) -> List[str]:
        keywords: List[str] = []
        role = self._normalize_keyword(str(profile.get("role") or ""))
        if role:
            keywords.append(role)
            keywords.extend(token for token in role.split() if len(token) > 2)

        keywords.extend([self._normalize_keyword(skill) for skill in current_skills if self._normalize_keyword(skill)])
        keywords.extend([self._normalize_keyword(keyword) for keyword in self.tools.tech_keywords if self._normalize_keyword(keyword)])

        seen = set()
        deduped: List[str] = []
        for keyword in keywords:
            if keyword and keyword not in seen:
                seen.add(keyword)
                deduped.append(keyword)
        return deduped[:50]

    def _source_evidence_count(self, skill: str) -> int:
        skill_norm = self._normalize_keyword(skill)
        count = 0
        for source_name, skills in self.tools.last_source_trends.items():
            if source_name == "role-trending":
                continue
            normalized = {self._normalize_keyword(s) for s in skills}
            if skill_norm in normalized:
                count += 1
        return count

    def _upward_skills(self, lifecycle: Dict[str, Dict], include_role_trending: bool = False) -> List[str]:
        scored: List[tuple[float, str]] = []
        for skill, detail in lifecycle.items():
            status = str(detail.get("status") or "stable")
            if status not in {"trending", "emerging"}:
                continue
            source = str(detail.get("source") or "")
            if not include_role_trending and source == "role-trending":
                continue
            confidence = float(detail.get("confidence") or 0.0)
            evidence = self._source_evidence_count(skill)
            if confidence < 0.4 and evidence < 2:
                continue
            score = confidence + (0.15 * evidence)
            scored.append((score, skill))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [skill for _, skill in scored]

    def _collect_role_standard_skills(self, role: str) -> List[str]:
        role_norm = self._normalize_keyword(role)
        standards: List[str] = []

        # 1) Curated role standards map.
        role_trending_map = default_role_trending_skills()
        for role_key, skills in role_trending_map.items():
            role_key_norm = self._normalize_keyword(role_key)
            if not role_key_norm:
                continue
            ratio = SequenceMatcher(None, role_norm, role_key_norm).ratio()
            if role_key_norm in role_norm or role_norm in role_key_norm or ratio >= 0.55:
                standards.extend([self._normalize_keyword(skill) for skill in skills])

        # 2) O*NET role skill lookup (live/fallback map).
        try:
            if self.tools.onet_repo and hasattr(self.tools.onet_repo, "get_skill_lookup_result"):
                lookup = self.tools.onet_repo.get_skill_lookup_result(role)
                standards.extend([
                    self._normalize_keyword(skill)
                    for skill in (lookup.get("skills", []) if isinstance(lookup, dict) else [])
                ])
        except Exception as exc:
            logger.debug("O*NET role standards lookup failed for '%s': %s", role, exc)

        # 3) ESCO role skill lookup (live/fallback map).
        try:
            if self.tools.esco_repo and hasattr(self.tools.esco_repo, "get_skill_lookup_result"):
                lookup = self.tools.esco_repo.get_skill_lookup_result(role)
                standards.extend([
                    self._normalize_keyword(skill)
                    for skill in (lookup.get("skills", []) if isinstance(lookup, dict) else [])
                ])
        except Exception as exc:
            logger.debug("ESCO role standards lookup failed for '%s': %s", role, exc)

        seen = set()
        unique: List[str] = []
        for skill in standards:
            if skill and skill not in seen:
                seen.add(skill)
                unique.append(skill)
        return unique

    def _role_relevance_score(
        self,
        skill: str,
        role: str,
        role_tokens: set[str],
        role_standards: List[str],
        lifecycle: Dict[str, Dict],
        current_skills: set[str],
    ) -> float:
        skill_norm = self._normalize_keyword(skill)
        source = str(lifecycle.get(skill, {}).get("source") or "")
        confidence = float(lifecycle.get(skill, {}).get("confidence") or 0.0)
        evidence = self._source_evidence_count(skill)
        tokens = set(self._tokenize(skill_norm))

        score = confidence + (0.15 * evidence)

        # Strongly weight role standards overlap.
        for standard in role_standards:
            if not standard:
                continue
            if standard == skill_norm:
                score += 2.4
                break
            if standard in skill_norm or skill_norm in standard:
                score += 1.6
                break
            if SequenceMatcher(None, skill_norm, standard).ratio() >= 0.8:
                score += 1.2
                break

        # Role lexical relevance.
        if role and (role in skill_norm or skill_norm in role):
            score += 1.3
        if role_tokens and (tokens & role_tokens):
            score += 1.0

        # Explicit role-trending source should be preferred.
        if source == "role-trending":
            score += 1.5

        # Prefer trends user does not already have for industry-readiness guidance.
        if skill_norm not in current_skills:
            score += 0.5

        # Penalize generic one-word skills that are not role-grounded.
        generic_terms = {
            "ai", "ml", "cloud", "data", "security", "api", "software", "development",
            "programming", "engineering", "frontend", "backend", "testing",
        }
        if skill_norm in generic_terms and source != "role-trending":
            score -= 1.4

        return score

    def _extract_role_specific_trends(self, profile: Dict, upward_skills: List[str], lifecycle: Dict[str, Dict]) -> List[str]:
        role = self._normalize_keyword(str(profile.get("role") or ""))
        if not role:
            return []

        role_tokens = {token for token in self._tokenize(role) if len(token) > 2}
        role_standards = self._collect_role_standard_skills(role)
        current_skills = {
            self._normalize_keyword(skill)
            for skill in (profile.get("skills", []) or [])
            if self._normalize_keyword(skill)
        }

        ranked: List[tuple[float, str]] = []
        upward_index = {
            self._normalize_keyword(skill): skill
            for skill in upward_skills
            if self._normalize_keyword(skill)
        }

        # Candidate pool = upward skills + role-template skills that also exist in lifecycle.
        candidate_order = list(upward_skills)
        for standard in role_standards:
            if standard in upward_index:
                candidate_skill = upward_index[standard]
                if candidate_skill not in candidate_order:
                    candidate_order.append(candidate_skill)

        for skill in candidate_order:
            # Keep only role-grounded candidates; this avoids copying generic trending output.
            skill_norm = self._normalize_keyword(skill)
            has_standard_match = any(
                standard == skill_norm
                or standard in skill_norm
                or skill_norm in standard
                or SequenceMatcher(None, skill_norm, standard).ratio() >= 0.8
                for standard in role_standards
            )
            if not has_standard_match and str(lifecycle.get(skill, {}).get("source") or "") != "role-trending":
                continue

            score = self._role_relevance_score(
                skill=skill,
                role=role,
                role_tokens=role_tokens,
                role_standards=role_standards,
                lifecycle=lifecycle,
                current_skills=current_skills,
            )
            # Hard threshold to avoid copying general trends verbatim.
            if score >= 2.2:
                ranked.append((score, skill))

        ranked.sort(key=lambda item: item[0], reverse=True)
        selected = [skill for _, skill in ranked]

        # If still sparse, use curated role standards that appear in upward signals.
        if len(selected) < 3 and role_standards:
            upward_norm = {self._normalize_keyword(skill): skill for skill in upward_skills}
            for standard in role_standards:
                if standard in upward_norm and upward_norm[standard] not in selected:
                    selected.append(upward_norm[standard])
                if len(selected) >= 8:
                    break

        # Preserve order + uniqueness + cap.
        seen = set()
        unique: List[str] = []
        for skill in selected:
            skill_norm = self._normalize_keyword(skill)
            if skill_norm and skill_norm not in seen:
                seen.add(skill_norm)
                unique.append(skill)

        return unique[:12]

    def _think_node(self, state: MarketAgentState) -> dict:
        state["messages"].append(AIMessage(content="[THINK] Build market signal aggregation plan"))
        state["current_step"] = "think"
        return state

    def _collect_node(self, state: MarketAgentState) -> dict:
        keywords = self._build_market_keywords(state["profile"], state["current_skills"])
        details = self.tools.collect_emerging_skills(keywords, role=str(state.get("profile", {}).get("role") or ""))
        state["emerging_skill_details"] = details
        state["messages"].append(
            AIMessage(content=f"[ACT] Collected {len(details)} market skills from {len(self.tools.last_source_health)} sources")
        )
        state["current_step"] = "collect"
        return state

    def _classify_node(self, state: MarketAgentState) -> dict:
        lifecycle = self.tools.classify_skill_lifecycle(state["emerging_skill_details"])
        for skill, detail in lifecycle.items():
            status = str(detail.get("status") or "stable")
            source = str(detail.get("source") or "")
            confidence = float(detail.get("confidence") or 0.0)
            evidence = self._source_evidence_count(skill)

            if status == "stable":
                if evidence >= 3:
                    status = "trending"
                elif evidence >= 2 or source == "role-trending":
                    status = "emerging"
                elif source in {"google", "github", "youtube", "google-fallback"} and confidence >= 0.65:
                    status = "emerging"
            elif status == "trending" and evidence <= 1 and source in {"google", "github", "youtube", "google-fallback"}:
                status = "emerging"

            if status not in {"trending", "emerging", "stable", "vanishing"}:
                status = "stable"
            detail["status"] = status

        state["lifecycle"] = lifecycle
        state["trending_skills"] = self._upward_skills(lifecycle, include_role_trending=False)[: self.max_emerging_skills]
        state["emerging_skills"] = [s for s, d in lifecycle.items() if d.get("status") == "emerging"]
        state["vanishing_skills"] = [s for s, d in lifecycle.items() if d.get("status") == "vanishing"]
        state["industry_trending_skills"] = self._upward_skills(lifecycle, include_role_trending=False)[: self.max_emerging_skills]
        state["messages"].append(
            AIMessage(
                content=(
                    f"[OBSERVE] Upward: {len(state['industry_trending_skills'])}, "
                    f"Vanishing: {len(state['vanishing_skills'])}"
                )
            )
        )
        state["current_step"] = "classify"
        return state

    def _compute_gaps_node(self, state: MarketAgentState) -> dict:
        # Get industry skills from non-role sources
        industry_skills = self._upward_skills(
            state["lifecycle"],
            include_role_trending=False,
        )
        # If no external sources, ALL role-trending skills are the industry trends
        if not industry_skills:
            industry_skills = self._upward_skills(state["lifecycle"], include_role_trending=True)
        state["industry_trending_skills"] = industry_skills[: self.max_emerging_skills]
        state["trending_skills"] = state["industry_trending_skills"]
        state["market_gaps"] = self.tools.compute_market_gaps(
            state["current_skills"],
            state["industry_trending_skills"],
            self.max_market_gaps,
        )
        # Use the original function which properly filters and ranks for role relevance
        role_specific = self._extract_role_specific_trends(
            state["profile"],
            self._upward_skills(state["lifecycle"], include_role_trending=True),
            state["lifecycle"],
        )
        state["role_specific_trends"] = role_specific
        state["messages"].append(AIMessage(content=f"[ACT] Computed {len(state['market_gaps'])} market gaps"))
        state["current_step"] = "compute_gaps"
        return state

    def _finalize_node(self, state: MarketAgentState) -> dict:
        state["messages"].append(AIMessage(content="[SUMMARY] Market analysis complete"))
        state["current_step"] = "complete"
        return state

    def analyze_market_gaps(self, profile: Dict) -> Dict:
        current_skills = [str(s).strip().lower() for s in profile.get("skills", []) if str(s).strip()]

        initial_state = MarketAgentState(
            profile=profile,
            current_skills=current_skills,
            emerging_skill_details={},
            lifecycle={},
            industry_trending_skills=[],
            market_gaps=[],
            trending_skills=[],
            vanishing_skills=[],
            emerging_skills=[],
            role_specific_trends=[],
            messages=[HumanMessage(content="Analyze market gaps")],
            current_step="",
            error=None,
            start_time=time.time(),
        )

        result = self.graph.invoke(initial_state)
        trending_skills_all = result.get("industry_trending_skills") or result.get("trending_skills") or []
        role_specific = result.get("role_specific_trends", [])
        payload = {
            "market_gaps": result["market_gaps"],
            "emerging_skills": result.get("emerging_skills", []),
            "trending_skills": trending_skills_all,
            "vanishing_skills": result["vanishing_skills"],
            "sources_used": sorted({v.get("source", "") for v in result["emerging_skill_details"].values() if v.get("source")}),
            "sources_attempted": sorted(self.tools.last_source_health.keys()),
            "current_role": str(profile.get("role") or ""),
            "keywords_used": [str(k).strip().lower() for k in self.tools.tech_keywords if str(k).strip()],
            "source_trends": self.tools.last_source_trends,
            "skill_details": result["emerging_skill_details"],
            "lifecycle": result["lifecycle"],
            "source_health": self.tools.last_source_health,
            "thought_process": [m.content for m in result["messages"]],
            # New: Role-specific trends
            "role_specific_trends": role_specific,
            "industry_trending_skills": trending_skills_all,
            "skill_gaps": result["market_gaps"],
        }
        validated = MarketAgentOutputSchema.model_validate(payload)
        return validated.model_dump()
