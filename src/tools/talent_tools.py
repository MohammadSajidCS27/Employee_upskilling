"""Talent matching tools for LangGraph/LangChain agents."""
import json
import logging
import re
from typing import Any, Dict, List

from src.services.dynamic_defaults import default_skill_catalog
from src.services.skill_normalizer import SkillNormalizer

logger = logging.getLogger(__name__)

class TalentTools:
    """Toolbox for job-skill extraction and candidate ranking."""

    def __init__(
        self,
        llm_client=None,
        skill_catalog: List[str] | None = None,
        skill_normalizer: SkillNormalizer | None = None,
    ):
        self.llm_client = llm_client
        self.skill_normalizer = skill_normalizer or SkillNormalizer()
        self.skill_catalog = self._canonicalize_list(skill_catalog or default_skill_catalog())

    def extract_required_skills(self, job_description: str) -> List[str]:
        if not isinstance(job_description, str):
            return []

        extracted: List[str] = []
        extracted.extend(self._extract_jd_skills_llm(job_description))
        extracted.extend(self._extract_jd_skills_catalog(job_description))
        return self._canonicalize_list(extracted)

    def rank_employees(
        self,
        employees: List[Dict[str, Any]],
        required_skills: List[str],
        max_matches: int,
    ) -> List[Dict[str, Any]]:
        req_skills = set(self._canonicalize_list(required_skills))
        matches: List[Dict[str, Any]] = []

        for employee in employees:
            emp_skills = set(self._canonicalize_list(employee.get("skills", [])))

            matched_skills = sorted([
                req for req in req_skills
                if any(self._skills_match(emp, req) for emp in emp_skills)
            ])

            missing_skills = sorted([
                s for s in req_skills
                if s not in matched_skills
            ])

            match_percentage = round(
                (len(matched_skills) / (len(req_skills) or 1)) * 100, 2
            )

            matches.append({
                "id":               employee.get("id"),
                "name":             employee.get("name", "Unknown"),
                "employee":         employee.get("name", "Unknown"),
                "match_percentage": match_percentage,   # ✅ consistent field name
                "matched_skills":   matched_skills,
                "missing_skills":   missing_skills,
                "total_required":   len(req_skills),
                "total_matched":    len(matched_skills),
            })

        # ✅ FIXED — sort by "match_percentage" not "score"
        matches.sort(key=lambda item: item["match_percentage"], reverse=True)
        return matches[: max(1, max_matches)]

    def _extract_jd_skills_catalog(self, job_description: str) -> List[str]:
        text_lower = job_description.lower()
        matched: List[str] = []
        for skill in self.skill_catalog:
            if not skill:
                continue
            # Boundary-aware match avoids false positives like "java" in "javascript".
            pattern = rf"(?<![a-z0-9]){re.escape(skill)}(?![a-z0-9])"
            if re.search(pattern, text_lower):
                matched.append(skill)
        return matched

    def _extract_jd_skills_llm(self, job_description: str) -> List[str]:
        if not self.llm_client:
            return []

        prompt = (
            "Extract all technical skills, tools, frameworks, cloud platforms, "
            "languages, and data technologies from the job description as a JSON "
            "array of lowercase skill strings.\n"
            "Rules:\n"
            "- Extract skills EXACTLY as written in the JD\n"
            "- Do NOT infer or expand (e.g. 'angular developer' → 'angular' only)\n"
            "- Do NOT include soft skills\n"
            "- Return ONLY a JSON array, no explanation\n\n"
            f"JOB DESCRIPTION:\n{job_description[:10000]}"
        )

        last_error: Exception | None = None
        for attempt in range(1, 3):
            try:
                response = self.llm_client.invoke(prompt)
                content = self._response_to_text(response)
                if not content:
                    return []
                parsed = self._parse_llm_list(content)
                return [item for item in self._canonicalize_list(parsed) if item]
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "LLM JD skill extraction attempt %d failed: %s",
                    attempt,
                    exc,
                )

        logger.warning(
            "LLM JD skill extraction disabled for this request after retries; using catalog-only extraction. Last error: %s",
            last_error,
        )
        return []

    def _response_to_text(self, response: Any) -> str:
        content = getattr(response, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text_value = item.get("text")
                    if isinstance(text_value, str):
                        parts.append(text_value)
            return "\n".join(part for part in parts if part)
        return ""

    def _parse_llm_list(self, content: str) -> List[str]:
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item).strip()]
            if isinstance(parsed, dict) and isinstance(parsed.get("skills"), list):
                return [str(item) for item in parsed.get("skills", []) if str(item).strip()]
        except Exception:
            pass

        fenced = re.search(r"```(?:json)?\s*($$[\s\S]*?$$)\s*```", content, re.IGNORECASE)
        if fenced:
            try:
                parsed = json.loads(fenced.group(1))
                if isinstance(parsed, list):
                    return [str(item) for item in parsed if str(item).strip()]
            except Exception:
                pass

        bracket = re.search(r"(\[[\s\S]*\])", content)
        if bracket:
            try:
                parsed = json.loads(bracket.group(1))
                if isinstance(parsed, list):
                    return [str(item) for item in parsed if str(item).strip()]
            except Exception:
                pass

        return [item.strip() for item in content.split(",") if item.strip()]

    def _normalize_skill(self, value: Any) -> str:
        text = " ".join(str(value).lower().strip().split())
        return re.sub(r"[^a-z0-9+.#\-/ ]", "", text)[:120]

    def _canonicalize_skill(self, value: Any) -> str:
        normalized = self._normalize_skill(value)
        if not normalized:
            return ""

        canonical = self.skill_normalizer.normalize(normalized)
        for base_skill, synonyms in self.skill_normalizer.synonym_map.items():
            if canonical == base_skill.lower():
                return base_skill.lower()
            if canonical in {self._normalize_skill(s) for s in synonyms}:
                return base_skill.lower()

        return canonical

    def _canonicalize_list(self, skills: List[Any]) -> List[str]:
        seen = set()
        ordered: List[str] = []
        for skill in skills:
            canonical = self._canonicalize_skill(skill)
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            ordered.append(canonical)
        return ordered

    def _skills_match(self, employee_skill: str, required_skill: str) -> bool:
        # ✅ Exact match first
        if employee_skill == required_skill:
            return True
        # ✅ Token subset match (e.g. "rest" matches "rest apis")
        emp_tokens = set(employee_skill.split())
        req_tokens = set(required_skill.split())
        if not emp_tokens or not req_tokens:
            return False
        return emp_tokens <= req_tokens or req_tokens <= emp_tokens