"""Skill Analysis Agent using LangGraph and LangChain."""
from difflib import SequenceMatcher
import logging
import re
from typing import TypedDict, List, Optional, Dict, Any
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from src.tools.skill_tools import SkillTools
from src.models.skill_gap_schema import SkillGapResponseSchema

logger = logging.getLogger(__name__)


class SkillAgentState(TypedDict):
    """State for skill analysis agent."""
    current_skills: List[str]
    target_role: str
    expected_skills: List[str]
    expected_skill_lookup: Dict[str, Any]
    experience_years: int
    gap_analysis: Dict
    skill_rankings: Dict
    readiness_assessment: Dict
    messages: List[BaseMessage]
    current_step: str
    error: Optional[str]


class SkillAgent:
    """Skill analysis agent using LangGraph."""

    PHRASE_CANONICAL_MAP = {
        "api gateway": "api gateway",
        "apigateway": "api gateway",
        "aip gateway": "api gateway",
        "micro service": "microservices",
        "micro services": "microservices",
        "micro-service": "microservices",
        "ci cd": "ci/cd",
        "cicd": "ci/cd",
        "continuous integration": "ci/cd",
        "continuous deployment": "ci/cd",
        "continuous integration continuous deployment": "ci/cd",
    }

    TOKEN_CANONICAL_MAP = {
        "apis": "api",
        "k8": "kubernetes",
        "k8s": "kubernetes",
        "microservice": "microservices",
        "micro-services": "microservices",
        "cicd": "ci/cd",
    }

    def __init__(self, workbook_repo=None, llm_client: Optional[Any] = None):
        self.llm = llm_client
        self.tools = SkillTools(workbook_repo=workbook_repo, llm_client=llm_client)
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph state machine."""
        graph = StateGraph(SkillAgentState)

        # Define nodes (reasoning and action steps)
        graph.add_node("think_strategy", self._think_strategy_node)
        graph.add_node("get_expected_skills", self._get_expected_skills_node)
        graph.add_node("analyze_gaps", self._analyze_gaps_node)
        graph.add_node("rank_skills", self._rank_skills_node)
        graph.add_node("assess_readiness", self._assess_readiness_node)
        graph.add_node("finalize_analysis", self._finalize_analysis_node)

        # Define edges
        graph.set_entry_point("think_strategy")
        graph.add_edge("think_strategy", "get_expected_skills")
        graph.add_edge("get_expected_skills", "analyze_gaps")
        graph.add_edge("analyze_gaps", "rank_skills")
        graph.add_edge("rank_skills", "assess_readiness")
        graph.add_edge("assess_readiness", "finalize_analysis")
        graph.add_edge("finalize_analysis", END)

        return graph.compile()

    def _think_strategy_node(self, state: SkillAgentState) -> dict:
        """Node: Agent thinks about analysis strategy."""
        logger.info(f"[AGENT-THINK] Analyzing skills for {state['target_role']}")
        thought = f"""
        Analyzing skill readiness for role: {state['target_role']}
        Current skills: {len(state['current_skills'])} skills
        
        Strategy:
        1. Fetch expected skills for {state['target_role']}
        2. Compare with current skills
        3. Identify gaps
        4. Rank by importance
        5. Assess readiness percentage
        """
        state["messages"].append(AIMessage(content=f"[THOUGHT] {thought}"))
        state["current_step"] = "think"
        logger.info(f"[AGENT-THINK] Strategy planned")
        return state

    def _get_expected_skills_node(self, state: SkillAgentState) -> dict:
        """Node: Fetch expected skills for role using tool."""
        logger.info(f"[AGENT-ACT] Fetching expected skills for {state['target_role']}")
        try:
            lookup = self.tools.get_expected_skill_lookup(
                state["target_role"],
                experience_years=int(state.get("experience_years", 0) or 0),
                current_skills=state.get("current_skills", []),
            )
            expected_skills = lookup.get("skills", [])

            lookup_source = str(lookup.get("source", ""))
            is_live = bool(lookup.get("live", False))
            provider = str(lookup.get("provider", "unknown"))
            if not is_live and provider != "workbook":
                logger.warning(
                    "Using non-live expected skill source for '%s' (provider=%s source=%s)",
                    state["target_role"],
                    provider,
                    lookup_source or "unknown",
                )

            state["expected_skills"] = expected_skills
            state["expected_skill_lookup"] = lookup
            state["messages"].append(
                AIMessage(
                    content=(
                        f"[ACTION] Fetched {len(expected_skills)} expected skills for {state['target_role']} "
                        f"(provider={lookup.get('provider', 'unknown')}, source={lookup.get('source', 'unknown')}, live={lookup.get('live', False)})"
                    )
                )
            )
            logger.info(f"[AGENT-ACT] Got {len(expected_skills)} expected skills")
            return state
        except Exception as e:
            state["error"] = str(e)
            logger.error(f"[AGENT-ERROR] Failed to get expected skills: {e}")
            raise

    def _analyze_gaps_node(self, state: SkillAgentState) -> dict:
        """Node: Analyze skill gaps using tool."""
        logger.info("[AGENT-ACT] Analyzing skill gaps")
        try:
            current_skills: List[str] = []
            for raw_skill in state.get("current_skills", []):
                for part in self._split_compound_skill(str(raw_skill or "")):
                    normalized = self._normalize_skill_name(part)
                    if normalized:
                        current_skills.append(normalized)
            current_skills = list(dict.fromkeys(current_skills))

            expected_skills = [
                self._normalize_skill_name(skill)
                for skill in state.get("expected_skills", [])
                if self._normalize_skill_name(skill)
            ]
            skill_levels = {
                self._normalize_skill_name(key): value
                for key, value in (state.get("expected_skill_lookup", {}).get("skill_levels", {}) or {}).items()
                if self._normalize_skill_name(key)
            }

            matched: List[str] = []
            partial: List[str] = []
            missing: List[str] = []
            required_points = 0
            achieved_points = 0

            for skill in expected_skills:
                required_level = self._required_level(skill, is_core=True, skill_levels=skill_levels)
                user_level = self._estimate_user_level(skill, current_skills)
                required_points += required_level
                achieved_points += min(user_level, required_level)

                if user_level >= required_level and user_level > 0:
                    matched.append(skill)
                elif user_level > 0:
                    partial.append(skill)
                else:
                    missing.append(skill)

            gap_analysis = {
                "matched_skills": matched,
                "partial_skills": partial,
                "missing_skills": missing,
                "readiness_score": round((achieved_points / required_points * 100) if required_points else 0.0, 2),
            }
            state["gap_analysis"] = gap_analysis
            state["messages"].append(
                AIMessage(content=f"[OBSERVATION] Readiness: {gap_analysis['readiness_score']}% | "
                                 f"Matched: {len(gap_analysis['matched_skills'])} | "
                                 f"Missing: {len(gap_analysis['missing_skills'])}")
            )
            logger.info(f"[AGENT-OBSERVE] Gap analysis complete: {gap_analysis['readiness_score']}% readiness")
            return state
        except Exception as e:
            state["error"] = str(e)
            logger.error(f"[AGENT-ERROR] Failed to analyze gaps: {e}")
            raise

    def _rank_skills_node(self, state: SkillAgentState) -> dict:
        """Node: Rank skills by importance using tool."""
        logger.info("[AGENT-ACT] Ranking skills by importance")
        try:
            skill_rankings = self.tools.rank_skills_by_importance(
                state["current_skills"],
                state["target_role"],
            )
            state["skill_rankings"] = skill_rankings
            state["messages"].append(
                AIMessage(content=f"[OBSERVATION] Core skills: {skill_rankings['core_count']} | "
                                 f"Soft skills: {len(skill_rankings['soft_skills'])}")
            )
            logger.info(f"[AGENT-OBSERVE] Skills ranked: {skill_rankings['core_count']} core, "
                       f"{len(skill_rankings['soft_skills'])} soft")
            return state
        except Exception as e:
            state["error"] = str(e)
            logger.error(f"[AGENT-ERROR] Failed to rank skills: {e}")
            raise

    def _assess_readiness_node(self, state: SkillAgentState) -> dict:
        """Node: Agent reflects on readiness assessment."""
        logger.info("[AGENT-REFLECT] Assessing overall readiness")
        
        readiness_score = state["gap_analysis"]["readiness_score"]
        
        if readiness_score >= 80:
            assessment = "Ready for immediate transition"
            level = "HIGH"
        elif readiness_score >= 60:
            assessment = "Can transition with focused learning (3-6 months)"
            level = "MEDIUM"
        elif readiness_score >= 40:
            assessment = "Significant learning needed (6-12 months)"
            level = "LOW"
        else:
            assessment = "Major career shift required (12+ months)"
            level = "VERY_LOW"
        
        state["readiness_assessment"] = {
            "level": level,
            "score": readiness_score,
            "assessment": assessment,
            "matched": len(state["gap_analysis"]["matched_skills"]),
            "missing": len(state["gap_analysis"]["missing_skills"]),
        }
        
        state["messages"].append(
            AIMessage(content=f"[REFLECTION] Readiness Level: {level} ({readiness_score}%)\n{assessment}")
        )
        logger.info(f"[AGENT-REFLECT] Assessment: {level} - {assessment}")
        return state

    def _finalize_analysis_node(self, state: SkillAgentState) -> dict:
        """Node: Finalize and summarize analysis."""
        logger.info("[AGENT-SUMMARIZE] Finalizing skill analysis")
        state["messages"].append(
            AIMessage(content="[SUMMARY] Skill analysis complete. Ready for next phase (learning path generation).")
        )
        state["current_step"] = "complete"
        logger.info("[AGENT-COMPLETE] Skill analysis finalized")
        return state

    def _normalize_skill_name(self, skill: str) -> str:
        value = str(skill or "").strip().lower()
        return re.sub(r"\s+", " ", value).strip()

    def _canonical_phrase(self, skill: str) -> str:
        normalized = self._normalize_skill_name(skill)
        if not normalized:
            return ""

        loose = re.sub(r"[_.\-]+", " ", normalized)
        loose = re.sub(r"\s*/\s*", " ", loose)
        loose = re.sub(r"\s+", " ", loose).strip()

        if loose in self.PHRASE_CANONICAL_MAP:
            return self.PHRASE_CANONICAL_MAP[loose]
        if normalized in self.PHRASE_CANONICAL_MAP:
            return self.PHRASE_CANONICAL_MAP[normalized]
        return normalized

    def _compressed_alnum(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", self._canonical_phrase(value))

    def _canonical_token(self, token: str) -> str:
        normalized = self._normalize_skill_name(token)
        return self.TOKEN_CANONICAL_MAP.get(normalized, normalized)

    def _split_compound_skill(self, skill: str) -> List[str]:
        value = self._canonical_phrase(skill)
        if not value:
            return []
        parts = re.split(r",|/|\||\band\b|\s*&\s*|;", value)
        cleaned = [self._canonical_phrase(part.strip()) for part in parts if part.strip()]
        return cleaned or [value]

    def _skill_variants(self, skill: str) -> set[str]:
        normalized = self._canonical_phrase(skill)
        if not normalized:
            return set()

        variants = {normalized}
        compressed = self._compressed_alnum(normalized)
        if len(compressed) >= 5:
            variants.add(compressed)
        for chunk in self._split_compound_skill(normalized):
            variants.add(chunk)
            chunk_compressed = self._compressed_alnum(chunk)
            if len(chunk_compressed) >= 5:
                variants.add(chunk_compressed)

        # Keep parenthetical alias and base text as variants.
        match = re.search(r"\(([^)]+)\)", normalized)
        if match:
            alias = match.group(1).strip()
            if alias:
                variants.add(alias)
                for chunk in self._split_compound_skill(alias):
                    variants.add(chunk)
            base = re.sub(r"\([^)]*\)", "", normalized).strip()
            if base:
                variants.add(base)

        return {item for item in variants if item}

    def _meaningful_tokens(self, skill: str) -> set[str]:
        text = self._canonical_phrase(skill)
        text = re.sub(r"[/_.\-]", " ", text)
        tokens = {
            self._canonical_token(token)
            for token in re.findall(r"[a-z0-9+.#-]+", text)
            if len(token) >= 2
        }
        stopwords = {
            "use", "using", "for", "and", "the", "with", "tools", "tool", "software", "skills", "skill",
            "development", "engineer", "developer", "fundamentals", "basics",
        }
        return {token for token in tokens if token not in stopwords}

    def _phrases_equivalent(self, left: str, right: str) -> bool:
        left_compact = self._compressed_alnum(left)
        right_compact = self._compressed_alnum(right)

        if not left_compact or not right_compact:
            return False
        if left_compact == right_compact:
            return True

        if min(len(left_compact), len(right_compact)) >= 5 and self._token_distance(left_compact, right_compact, max_distance=1) <= 1:
            return True

        if (
            min(len(left_compact), len(right_compact)) >= 6
            and left_compact[0] == right_compact[0]
            and SequenceMatcher(None, left_compact, right_compact).ratio() >= 0.85
        ):
            return True

        return False

    def _token_distance(self, left: str, right: str, max_distance: int = 1) -> int:
        """Bounded Damerau-Levenshtein distance for short skill tokens."""
        if left == right:
            return 0
        if not left or not right:
            return max(len(left), len(right))
        if abs(len(left) - len(right)) > max_distance:
            return max_distance + 1

        rows = len(left) + 1
        cols = len(right) + 1
        dp = [[0] * cols for _ in range(rows)]
        for i in range(rows):
            dp[i][0] = i
        for j in range(cols):
            dp[0][j] = j

        for i in range(1, rows):
            row_min = max_distance + 1
            for j in range(1, cols):
                cost = 0 if left[i - 1] == right[j - 1] else 1
                dp[i][j] = min(
                    dp[i - 1][j] + 1,
                    dp[i][j - 1] + 1,
                    dp[i - 1][j - 1] + cost,
                )
                if (
                    i > 1 and j > 1
                    and left[i - 1] == right[j - 2]
                    and left[i - 2] == right[j - 1]
                ):
                    dp[i][j] = min(dp[i][j], dp[i - 2][j - 2] + 1)
                row_min = min(row_min, dp[i][j])
            if row_min > max_distance:
                return max_distance + 1

        return dp[-1][-1]

    def _tokens_equivalent(self, left: str, right: str) -> bool:
        if left == right:
            return True
        if not left or not right:
            return False

        min_length = min(len(left), len(right))
        if min_length < 3:
            return False

        if self._token_distance(left, right, max_distance=1) <= 1:
            return True

        # Fallback for slightly longer noisy tokens without becoming too permissive.
        if min_length >= 4 and SequenceMatcher(None, left, right).ratio() >= 0.78:
            return True

        return False

    def _fuzzy_overlap_count(self, expected_tokens: set[str], current_tokens: set[str]) -> int:
        remaining = set(current_tokens)
        matches = 0
        for expected in expected_tokens:
            direct = next((token for token in remaining if token == expected), None)
            if direct is not None:
                remaining.remove(direct)
                matches += 1
                continue

            fuzzy = next((token for token in remaining if self._tokens_equivalent(expected, token)), None)
            if fuzzy is not None:
                remaining.remove(fuzzy)
                matches += 1
        return matches

    def _estimate_user_level(self, skill: str, current_skills: List[str]) -> int:
        expected_variants = self._skill_variants(skill)
        expected_tokens = self._meaningful_tokens(skill)
        expected_synonyms = set(self.tools.skill_normalizer.get_similar_skills(skill))

        expanded_current_skills = list(current_skills)
        expanded_current_tokens = {}
        for current in current_skills:
            synonyms = self.tools.skill_normalizer.get_similar_skills(current)
            expanded_current_skills.extend(synonyms)
            expanded_current_tokens[current] = self._meaningful_tokens(current) | set(synonyms)

        best_level = 0
        for current in expanded_current_skills:
            current_variants = self._skill_variants(current)
            if expected_variants & current_variants:
                return 4

            if any(
                self._phrases_equivalent(expected_variant, current_variant)
                for expected_variant in expected_variants
                for current_variant in current_variants
            ):
                return 4

            # Check if current is a synonym of expected
            if current.lower() in {s.lower() for s in expected_synonyms}:
                return 4

            # Strong substring containment: "react" in "react.js", "html" in "semantic html", etc.
            for expected_variant in expected_variants:
                for current_variant in current_variants:
                    if not expected_variant or not current_variant:
                        continue
                    expected_clean = re.sub(r'[^a-z0-9]', '', expected_variant.lower())
                    current_clean = re.sub(r'[^a-z0-9]', '', current_variant.lower())
                    if expected_clean and current_clean:
                        if expected_clean in current_clean or current_clean in expected_clean:
                            return 4

            # Deterministic alias containment for entries like "containerization (docker)".
            for expected_variant in expected_variants:
                for current_variant in current_variants:
                    if not expected_variant or not current_variant:
                        continue
                    if len(expected_variant) >= 4 and expected_variant in current_variant:
                        return 3
                    if len(current_variant) >= 4 and current_variant in expected_variant:
                        best_level = max(best_level, 2)

            current_tokens = self._meaningful_tokens(current)
            if not expected_tokens or not current_tokens:
                continue
            overlap_count = self._fuzzy_overlap_count(expected_tokens, current_tokens)
            if not overlap_count:
                continue

            precision = overlap_count / max(1, len(expected_tokens))
            recall = overlap_count / max(1, len(current_tokens))

            if precision >= 0.9 and recall >= 0.9:
                return 4
            if precision >= 0.6:
                return 3
            if precision >= 0.35 or recall >= 0.5:
                best_level = max(best_level, 2)

        return best_level

    def _skill_category(self, skill: str) -> str:
        normalized = self._normalize_skill_name(skill)
        if "language" in normalized:
            return "languages"
        if any(token in normalized for token in ["framework", "library", "platform"]):
            return "frameworks"
        if any(token in normalized for token in ["tool", "service", "api", "cloud"]):
            return "tools"
        return "general"

    def _category_for(self, skill: str, skill_to_heading: Dict[str, str]) -> str:
        """Prefer the source's own grouping (workbook/LLM heading); fall back to heuristic."""
        normalized = self._normalize_skill_name(skill)
        heading = skill_to_heading.get(normalized)
        if heading:
            return str(heading).strip().lower()
        return self._skill_category(skill)

    def _matching_resume_skills(self, skill: str, current_skills: List[str]) -> List[str]:
        """Resume skills that share evidence with the expected skill (no fabrication)."""
        expected_tokens = self._meaningful_tokens(skill)
        expected_clean = re.sub(r"[^a-z0-9]", "", skill.lower())
        matches: List[str] = []
        for current in current_skills:
            current_clean = re.sub(r"[^a-z0-9]", "", current.lower())
            shared = expected_tokens & self._meaningful_tokens(current)
            if shared or (expected_clean and current_clean and (expected_clean in current_clean or current_clean in expected_clean)):
                matches.append(current)
        return list(dict.fromkeys(matches))

    def _evidence_for(self, skill: str, current_skills: List[str], user_level: int) -> str:
        """Factual evidence string grounded only in the candidate's resume skills."""
        if user_level <= 0:
            return f"No mention of '{skill}' or related skills found in the resume."
        related = self._matching_resume_skills(skill, current_skills)
        if related:
            return f"Resume references {', '.join(related[:3])}, partially covering '{skill}'."
        return f"Resume shows partial familiarity with '{skill}'."

    def _required_level(self, skill: str, is_core: bool, skill_levels: Optional[Dict[str, Any]] = None) -> int:
        normalized_skill = self._normalize_skill_name(skill)
        if skill_levels and normalized_skill in skill_levels:
            try:
                mapped = int(skill_levels.get(normalized_skill, 0) or 0)
                if mapped > 0:
                    return max(1, min(mapped, 4))
            except Exception:
                pass
        return 4 if is_core else 3

    def _readiness_category(self, score: float) -> tuple[str, str]:
        if score >= 80:
            return "ready_now", "Ready to transition with minimal support"
        if score >= 60:
            return "transition_ready", "Can transition with focused learning"
        if score >= 40:
            return "developing", "Significant learning needed"
        return "early_stage", "Good starting point, structured plan needed"

    def _build_skill_dependencies(
        self,
        missing_core_skills: List[Dict[str, Any]],
        expected_skills: List[str],
        current_skills: List[str],
        use_related_lookup: bool = True,
    ) -> Dict[str, Dict[str, Any]]:
        dependencies: Dict[str, Dict[str, Any]] = {}
        expected_set = set(expected_skills)
        current_set = set(current_skills)

        for item in missing_core_skills:
            skill = item.get("skill", "")
            related: List[str] = []
            esco_repo = getattr(self.tools, "esco_repo", None)
            if use_related_lookup and esco_repo and hasattr(esco_repo, "get_related_skills"):
                try:
                    related = [
                        self._normalize_skill_name(value)
                        for value in esco_repo.get_related_skills(skill)
                        if self._normalize_skill_name(value)
                    ]
                except Exception as error:
                    logger.warning("Related skill lookup failed for '%s': %s", skill, error)

            requires = []
            for value in related:
                if value in expected_set and value != self._normalize_skill_name(skill) and value not in requires:
                    requires.append(value)
                if len(requires) == 3:
                    break

            dependency_met = all(req in current_set for req in requires)
            missing_dependencies = [req for req in requires if req not in current_set]
            dependencies[skill] = {
                "requires": requires,
                "dependency_met": dependency_met,
                "missing_dependencies": missing_dependencies,
                "dependency_score": 1.0 if not requires else round((len(requires) - len(missing_dependencies)) / len(requires), 2),
            }
        return dependencies

    def _derive_optional_skills(self, expected_skills: List[str], current_skills: List[str]) -> List[str]:
        optional: List[str] = []
        seen = set(expected_skills)
        esco_repo = getattr(self.tools, "esco_repo", None)
        if not esco_repo or not hasattr(esco_repo, "get_related_skills"):
            return optional

        for skill in expected_skills[:5]:
            try:
                related = [
                    self._normalize_skill_name(value)
                    for value in esco_repo.get_related_skills(skill)
                    if self._normalize_skill_name(value)
                ]
            except Exception as error:
                logger.warning("Optional related skill lookup failed for '%s': %s", skill, error)
                continue

            for related_skill in related:
                if related_skill in seen or related_skill in current_skills:
                    continue
                seen.add(related_skill)
                optional.append(related_skill)
                if len(optional) >= 5:
                    return optional

        return optional

    def _build_recommendations(
        self,
        target_role: str,
        core_gaps: List[str],
        partial_skills: List[str],
        readiness_score: float,
    ) -> Dict[str, List[str]]:
        immediate_actions: List[str] = []
        if partial_skills:
            immediate_actions.append(f"Strengthen {partial_skills[0]} to close the current partial gap")
        if core_gaps:
            immediate_actions.append(f"Start {core_gaps[0]} immediately because it blocks {target_role}")
        if not immediate_actions:
            immediate_actions.append(f"Review the {target_role} skill profile and validate current strengths")

        short_term_goals: List[str] = []
        for skill in core_gaps[:3]:
            short_term_goals.append(f"Reach working proficiency in {skill} for the {target_role} path")
        if not short_term_goals:
            short_term_goals.append(f"Build one project aligned to {target_role} requirements")

        long_term_goals = [
            f"Complete a production-ready project for the {target_role} role",
            f"Reach readiness above 80% for {target_role}",
            f"Use Git-based workflows and document progress consistently",
        ]

        if readiness_score < 40:
            long_term_goals.insert(0, f"Focus on the foundational skills required for {target_role}")

        return {
            "immediate_actions": immediate_actions,
            "short_term_goals": short_term_goals,
            "long_term_goals": long_term_goals,
        }

    def _format_skill_gap_output(
        self,
        result: Dict[str, Any],
        user_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        current_skills: List[str] = []
        for raw_skill in result.get("current_skills", []):
            for part in self._split_compound_skill(str(raw_skill or "")):
                normalized = self._normalize_skill_name(part)
                if normalized:
                    current_skills.append(normalized)
        current_skills = list(dict.fromkeys(current_skills))
        target_role = str(result.get("target_role") or (user_profile or {}).get("role") or "Unknown Role")
        profile = user_profile or {}

        profile_payload = {
            "employee_id": profile.get("employee_id", "EMP001"),
            "name": profile.get("name", "Unknown"),
            "current_role": profile.get("current_role") or profile.get("role") or "Unknown",
            "experience_years": profile.get("experience_years", profile.get("experience", 0)),
        }

        expected_skills = [self._normalize_skill_name(skill) for skill in result.get("expected_skills", []) if self._normalize_skill_name(skill)]
        source_lookup = result.get("expected_skill_lookup", {})
        source_provider = str(source_lookup.get("provider", "")).strip().lower()
        skill_levels = {
            self._normalize_skill_name(key): value
            for key, value in (source_lookup.get("skill_levels", {}) or {}).items()
            if self._normalize_skill_name(key)
        }
        headings_map = source_lookup.get("headings", {}) or {}
        skill_to_heading: Dict[str, str] = {}
        for heading, heading_skills in headings_map.items():
            for hs in heading_skills or []:
                normalized_hs = self._normalize_skill_name(hs)
                if normalized_hs:
                    skill_to_heading[normalized_hs] = heading
        source_value = str(source_lookup.get("source", ""))
        if (
            source_lookup
            and source_provider != "workbook"
            and not bool(source_lookup.get("live", False))
            and source_value not in {"esco_direct", "onet_direct"}
        ):
            logger.warning(
                "Non-live skill source used for role '%s': provider=%s source=%s",
                target_role,
                source_lookup.get("provider", "unknown"),
                source_value or "unknown",
            )

        matched_skills: List[str] = []
        skill_gaps: List[Dict[str, Any]] = []
        missing_core_skills: List[Dict[str, Any]] = []
        missing_optional_skills: List[Dict[str, Any]] = []

        expected_skill_set = set(expected_skills)
        optional_candidates = [] if source_provider == "workbook" else self._derive_optional_skills(expected_skills, current_skills)

        for skill in expected_skills:
            user_level = self._estimate_user_level(skill, current_skills)
            required_level = self._required_level(skill, is_core=True, skill_levels=skill_levels)
            if user_level >= required_level and user_level > 0:
                matched_skills.append(skill)
            elif user_level > 0:
                skill_gaps.append(
                    {
                        "skill": skill,
                        "user_level": user_level,
                        "required_level": required_level,
                        "gap": required_level - user_level,
                        "priority": "high" if required_level - user_level <= 1 else "critical",
                        "importance": "core",
                        "category": self._category_for(skill, skill_to_heading),
                        "evidence": self._evidence_for(skill, current_skills, user_level),
                        "status": "in_progress",
                    }
                )
            else:
                required = self._required_level(skill, is_core=True, skill_levels=skill_levels)
                entry = {
                    "skill": skill,
                    "user_level": 0,
                    "required_level": required,
                    "gap": required,
                    "priority": "critical",
                    "importance": "core",
                    "category": self._category_for(skill, skill_to_heading),
                    "evidence": self._evidence_for(skill, current_skills, 0),
                    "status": "locked",
                }
                missing_core_skills.append(entry)

        for skill in optional_candidates:
            if skill in expected_skill_set:
                continue
            missing_optional_skills.append(
                {
                    "skill": skill,
                    "user_level": 0,
                    "required_level": self._required_level(skill, is_core=False),
                    "gap": self._required_level(skill, is_core=False),
                    "priority": "medium",
                    "importance": "optional",
                    "category": self._category_for(skill, skill_to_heading),
                    "evidence": self._evidence_for(skill, current_skills, 0),
                    "status": "missing",
                }
            )

        skill_dependencies = self._build_skill_dependencies(
            missing_core_skills,
            expected_skills,
            current_skills,
            use_related_lookup=source_provider != "workbook",
        )
        core_gaps = [item["skill"] for item in missing_core_skills + skill_gaps]
        required_points = sum(int(self._required_level(skill, is_core=True, skill_levels=skill_levels)) for skill in expected_skills)
        achieved_points = float(sum(int(self._required_level(skill, is_core=True, skill_levels=skill_levels)) for skill in matched_skills))
        achieved_points += float(sum(int(item.get("user_level", 0)) for item in skill_gaps))

        # Blended (category) credit: a candidate who demonstrably covers part of a skill
        # area is partially ready for the remaining skills in that same area. Without this
        # a genuine practitioner scores near-zero against a highly specialized role matrix
        # (e.g. a microservices sheet) simply because they lack a few niche topics.
        covered_skills = set(matched_skills) | {item.get("skill") for item in skill_gaps}
        heading_total: Dict[str, int] = {}
        heading_covered: Dict[str, int] = {}
        for skill in expected_skills:
            heading = skill_to_heading.get(self._normalize_skill_name(skill))
            if not heading:
                continue
            heading_total[heading] = heading_total.get(heading, 0) + 1
            if skill in covered_skills:
                heading_covered[heading] = heading_covered.get(heading, 0) + 1

        blend_factor = 0.5
        for item in missing_core_skills:
            heading = skill_to_heading.get(self._normalize_skill_name(item.get("skill", "")))
            total_in_heading = heading_total.get(heading, 0) if heading else 0
            if not total_in_heading:
                continue
            familiarity = heading_covered.get(heading, 0) / total_in_heading
            if familiarity <= 0:
                continue
            achieved_points += familiarity * blend_factor * int(
                self._required_level(item.get("skill", ""), is_core=True, skill_levels=skill_levels)
            )

        # Optional skills do not affect mandatory readiness denominator.
        readiness_score = round(min(100.0, (achieved_points / required_points * 100)) if required_points else 0.0, 2)
        readiness_category, readiness_message = self._readiness_category(readiness_score)
        skills_missing_total = len(missing_core_skills) + len(missing_optional_skills)
        skills_partial_total = len(skill_gaps)

        readiness_summary = {
            "readiness_score": readiness_score,
            "readiness_category": readiness_category,
            "readiness_message": readiness_message,
            "total_skills_required": len(expected_skills),
            "skills_completed": len(matched_skills),
            "skills_partial": skills_partial_total,
            "skills_missing": skills_missing_total,
        }

        skill_analysis = {
            "matched_skills": matched_skills,
            "skill_gaps": skill_gaps,
            "missing_core_skills": missing_core_skills,
            "missing_optional_skills": missing_optional_skills,
            "priority_skills": sorted(
                [
                    {
                        "skill": item["skill"],
                        "priority_rank": index + 1,
                        "priority": item["priority"],
                        "gap": item["gap"],
                        "category": item["category"],
                    }
                    for index, item in enumerate(missing_core_skills + skill_gaps + missing_optional_skills)
                ],
                key=lambda item: (0 if item["priority"] == "critical" else 1 if item["priority"] == "high" else 2, -item["gap"], item["priority_rank"]),
            ),
        }

        skill_to_heading: Dict[str, str] = {}
        for heading, skills in headings_map.items():
            for skill in skills:
                normalized = self._normalize_skill_name(skill)
                if normalized:
                    skill_to_heading[normalized] = heading

        core_gaps_by_heading: Dict[str, List[str]] = {}
        for item in missing_core_skills:
            skill = item.get("skill", "")
            heading = skill_to_heading.get(self._normalize_skill_name(skill))
            if heading:
                core_gaps_by_heading.setdefault(heading, []).append(skill)
        for item in skill_gaps:
            skill = item.get("skill", "")
            heading = skill_to_heading.get(self._normalize_skill_name(skill))
            if heading:
                core_gaps_by_heading.setdefault(heading, []).append(skill)

        payload = {
            "user_profile": profile_payload,
            "readiness_summary": readiness_summary,
            "skill_analysis": skill_analysis,
            "skill_dependencies": skill_dependencies,
            "core_gaps": core_gaps,
            "core_gaps_by_heading": core_gaps_by_heading,
            "skill_source": {
                "provider": source_lookup.get("provider", "unknown"),
                "source": source_lookup.get("source", "unknown"),
                "live": bool(source_lookup.get("live", False)),
                "workbook_file": source_lookup.get("workbook_file", "") or "",
                "sheet": source_lookup.get("sheet", "") or "",
            },
            "recommendations": self._build_recommendations(target_role, core_gaps, [item["skill"] for item in skill_gaps], readiness_score),
        }
        validated = SkillGapResponseSchema.model_validate(payload)
        return validated.model_dump()

    def analyze_skills(self, current_skills: List[str], role: str, user_profile: Optional[Dict[str, Any]] = None) -> dict:
        """Analyze skills for the user-confirmed role."""
        profile = user_profile or {}
        experience_years = int(profile.get("experience_years", profile.get("experience", 0)) or 0)
        initial_state = SkillAgentState(
            current_skills=current_skills,
            target_role=role,
            expected_skills=[],
            expected_skill_lookup={},
            experience_years=experience_years,
            gap_analysis={},
            skill_rankings={},
            readiness_assessment={},
            messages=[HumanMessage(content=f"Analyze skills for {role}")],
            current_step="",
            error=None,
        )

        logger.info(f"[AGENT] Starting skill analysis for {role}...")
        result = self.graph.invoke(initial_state)
        return self._format_skill_gap_output(result, user_profile=user_profile)
