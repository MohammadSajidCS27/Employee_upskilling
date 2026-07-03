import logging
import re
from typing import Dict, List, Optional, Set

import requests

from src.services.dynamic_defaults import default_market_keywords, default_role_trending_skills

logger = logging.getLogger(__name__)


class JobMarketSignalsAPI:
    """Collect role-driven skill signals from public job-market sources.

    This service intentionally uses publicly accessible feeds/APIs and avoids scraping
    gated platforms directly. It complements ESCO/O*NET and trend APIs with
    current job-demand evidence.
    """

    def __init__(self):
        self.request_timeout_seconds = 2
        self.max_jobs_per_source = 40
        self._skill_universe = self._build_skill_universe()

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(str(value or "").strip().lower().split())

    @staticmethod
    def _build_skill_universe() -> Set[str]:
        universe: Set[str] = set(default_market_keywords())
        for _, skills in default_role_trending_skills().items():
            universe.update(JobMarketSignalsAPI._normalize(skill) for skill in skills if JobMarketSignalsAPI._normalize(skill))
        return {skill for skill in universe if skill}

    def _extract_known_skills(self, text: str) -> List[str]:
        haystack = f" {self._normalize(text)} "
        found: List[str] = []
        for skill in self._skill_universe:
            pattern = r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])"
            if re.search(pattern, haystack):
                found.append(skill)
        # prioritize longer, more specific skills first
        found.sort(key=lambda value: (-len(value), value))
        seen = set()
        unique: List[str] = []
        for skill in found:
            if skill not in seen:
                seen.add(skill)
                unique.append(skill)
        return unique

    def _fetch_remotive(self, role: str) -> List[str]:
        try:
            response = requests.get(
                "https://remotive.com/api/remote-jobs",
                params={"search": role},
                timeout=self.request_timeout_seconds,
            )
            if response.status_code != 200:
                return []
            payload = response.json() if response.content else {}
            jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
            skills: List[str] = []
            for job in jobs[: self.max_jobs_per_source]:
                title = str(job.get("title", ""))
                tags = " ".join([str(tag) for tag in (job.get("tags", []) or [])])
                description = str(job.get("description", ""))[:4000]
                blob = f"{title} {tags} {description}"
                skills.extend(self._extract_known_skills(blob))
            return skills
        except Exception as exc:
            logger.debug("Remotive job-market fetch failed: %s", exc)
            return []

    def _fetch_arbeitnow(self, role: str) -> List[str]:
        try:
            response = requests.get(
                "https://www.arbeitnow.com/api/job-board-api",
                timeout=self.request_timeout_seconds,
            )
            if response.status_code != 200:
                return []
            payload = response.json() if response.content else {}
            jobs = payload.get("data", []) if isinstance(payload, dict) else []
            role_tokens = set(self._normalize(role).split())

            skills: List[str] = []
            for job in jobs[: self.max_jobs_per_source]:
                title = str(job.get("title", ""))
                description = str(job.get("description", ""))[:3000]
                tags = " ".join([str(tag) for tag in (job.get("tags", []) or [])])
                blob = f"{title} {tags} {description}"
                blob_norm = self._normalize(blob)

                # lightly filter by role relevance when role terms exist
                if role_tokens and not any(token in blob_norm for token in role_tokens if len(token) > 2):
                    continue

                skills.extend(self._extract_known_skills(blob))
            return skills
        except Exception as exc:
            logger.debug("Arbeitnow job-market fetch failed: %s", exc)
            return []

    def get_role_market_skills(self, role: str, keywords: Optional[List[str]] = None) -> List[str]:
        role_norm = self._normalize(role)
        if not role_norm:
            return []

        merged: List[str] = []
        merged.extend(self._fetch_remotive(role_norm))
        merged.extend(self._fetch_arbeitnow(role_norm))

        # Add role-keyword extraction fallback against the provided search keywords.
        for keyword in keywords or []:
            merged.extend(self._extract_known_skills(str(keyword)))

        # If all APIs failed, use internal fallback based on skill universe
        if not merged:
            merged = self._get_fallback_skills(role_norm)

        seen = set()
        unique: List[str] = []
        for skill in merged:
            normalized = self._normalize(skill)
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique.append(normalized)
        return unique[:50]

    def _get_fallback_skills(self, role: str) -> List[str]:
        """Fallback skills extracted from skill universe when APIs fail."""
        skills = []
        role_tokens = set(role.split())
        for skill in self._skill_universe:
            skill_tokens = set(skill.split())
            if role_tokens and role_tokens & skill_tokens:
                skills.append(skill)
        # If nothing matches, return top generic market skills
        if not skills:
            skills = list(default_market_keywords())[:20]
        return skills
