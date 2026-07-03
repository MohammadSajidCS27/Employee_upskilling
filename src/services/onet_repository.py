import requests
import logging
from typing import List, Optional, Dict
import json
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

class ONETRepository:
    def __init__(
        self,
        api_key: Optional[str] = None,
        esco_repo=None,
        trending_skills: Optional[List[str]] = None,
        occupation_skill_map: Optional[Dict[str, List[str]]] = None,
    ):
        self.api_key = api_key
        self.esco_repo = esco_repo
        self.trending_skills = [skill.strip().lower() for skill in (trending_skills or []) if skill.strip()]
        self.occupation_skill_map = {
            str(key).strip().lower(): [str(skill).strip().lower() for skill in value if str(skill).strip()]
            for key, value in (occupation_skill_map or {}).items()
            if isinstance(value, list)
        }
        if api_key:
            self.headers = {"Accept": "application/json"}
            self.auth = (api_key, "X")
        else:
            self.headers = {}
            self.auth = None

    def get_trending_skills(self) -> List[str]:
        return list(self.trending_skills)

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(str(value).lower().strip().split())

    @staticmethod
    def _tokenize(value: str) -> List[str]:
        normalized = ONETRepository._normalize_text(value)
        tokens = [token.strip(".,:/()[]{}") for token in normalized.split()]
        return [token for token in tokens if token]

    @staticmethod
    def _specific_tokens(value: str) -> List[str]:
        generic_tokens = {
            "senior", "junior", "lead", "principal", "staff", "engineer", "developer",
            "specialist", "expert", "manager", "associate", "architect",
        }
        tokens = ONETRepository._tokenize(value)
        specific = [token for token in tokens if token not in generic_tokens]
        return specific or tokens

    def _occupation_label(self, occupation: Dict) -> str:
        return (
            occupation.get("title")
            or occupation.get("name")
            or occupation.get("occupation")
            or occupation.get("description")
            or ""
        )

    def _occupation_code(self, occupation: Dict) -> str:
        return (
            occupation.get("code")
            or occupation.get("onetsoc_code")
            or occupation.get("occupation_code")
            or occupation.get("id")
            or ""
        )

    def _occupation_score(self, occupation: Dict, target_title: str) -> float:
        target = self._normalize_text(target_title)
        label = self._normalize_text(self._occupation_label(occupation))
        ratio = SequenceMatcher(None, target, label).ratio()
        target_tokens = set(self._specific_tokens(target))
        label_tokens = set(self._tokenize(label))
        overlap = len(target_tokens & label_tokens)
        overlap_ratio = overlap / max(1, len(target_tokens))
        score = ratio + (1.4 * overlap_ratio)
        if target and target in label:
            score += 1.0
        if overlap and all(token in label_tokens for token in target_tokens):
            score += 1.0

        software_markers = {"software", "backend", "frontend", "fullstack", "full-stack", "web", "application"}
        unrelated_for_software = {
            "satellite", "aerospace", "industrial", "mineral", "electrical", "optoelectronic",
            "mechatronics", "microsystem", "ship", "marine", "mechanical",
        }
        target_is_software = bool(set(self._tokenize(target)) & software_markers)
        if target_is_software:
            if label_tokens & software_markers:
                score += 1.0
            if label_tokens & unrelated_for_software:
                score -= 1.3

        return score

    def _best_occupation_match(self, occupations: List[Dict], target_title: str) -> Optional[Dict]:
        if not occupations:
            return None
        scored = sorted(occupations, key=lambda item: self._occupation_score(item, target_title), reverse=True)
        best = scored[0]
        if self._occupation_score(best, target_title) < 0.25:
            return None
        return best

    @staticmethod
    def _extract_skills_from_details(details: Dict) -> List[str]:
        if not isinstance(details, dict):
            return []

        skills: List[str] = []

        # Common O*NET response patterns.
        direct = details.get("skills")
        if isinstance(direct, list):
            for item in direct:
                if isinstance(item, dict):
                    value = item.get("name") or item.get("title") or item.get("element_name") or item.get("skill")
                    if value:
                        skills.append(str(value).strip().lower())
                elif isinstance(item, str):
                    skills.append(item.strip().lower())

        elements = details.get("element")
        if isinstance(elements, list):
            for item in elements:
                if not isinstance(item, dict):
                    continue
                category = str(item.get("category", "")).lower()
                if category and "skill" not in category:
                    continue
                value = item.get("name") or item.get("title") or item.get("element_name")
                if value:
                    skills.append(str(value).strip().lower())

        # De-duplicate while preserving order.
        unique: List[str] = []
        seen = set()
        for skill in skills:
            if skill and skill not in seen:
                seen.add(skill)
                unique.append(skill)
        return unique

    def get_skills_for_occupation(self, occupation_title: str) -> List[str]:
        return self.get_skill_lookup_result(occupation_title)["skills"]

    def get_skill_lookup_result(self, occupation_title: str) -> Dict[str, object]:
        title_lower = occupation_title.lower()

        # 1) Live O*NET API path when credentials are available.
        if self.api_key:
            try:
                occupations = self.search_occupation(occupation_title)
                best = self._best_occupation_match(occupations, occupation_title)
                if best:
                    code = self._occupation_code(best)
                    details = self.get_occupation_details(code)
                    extracted = self._extract_skills_from_details(details)
                    if extracted:
                        logger.info("Retrieved %s O*NET skills for '%s'", len(extracted), occupation_title)
                        return {
                            "skills": extracted,
                            "source": "onet_live",
                            "live": True,
                        }
            except Exception as e:
                logger.error(f"ONET skill retrieval failed: {e}")

        # 2) Configurable occupation map fallback.
        for key, skills in self.occupation_skill_map.items():
            if key in title_lower:
                logger.info("Using O*NET occupation map fallback for '%s'", occupation_title)
                return {
                    "skills": skills,
                    "source": "onet_role_map",
                    "live": False,
                }

        # 3) Cross-source fallback to ESCO when available.
        if self.esco_repo:
            esco_result = self.esco_repo.get_skill_lookup_result(occupation_title)
            esco_skills = esco_result.get("skills", []) if isinstance(esco_result, dict) else []
            if esco_skills:
                logger.info("Using ESCO fallback through O*NET repository for '%s'", occupation_title)
                return {
                    "skills": [str(skill).strip().lower() for skill in esco_skills if str(skill).strip()],
                    "source": "esco_via_onet_fallback",
                    "live": False,
                }

        return {
            "skills": [],
            "source": "unavailable",
            "live": False,
        }

    def search_occupation(self, keyword: str) -> List[Dict]:
        if self.api_key:
            try:
                response = requests.get(
                    "https://services.onetcenter.org/ws/online/occupations",
                    params={"keyword": keyword},
                    auth=self.auth,
                    headers=self.headers,
                    timeout=10,
                )
                if response.status_code == 200:
                    data = response.json()
                    occupations = data.get("occupation")
                    if isinstance(occupations, list):
                        return occupations
                    embedded = data.get("occupations")
                    if isinstance(embedded, list):
                        return embedded
            except Exception as e:
                logger.error(f"ONET API error: {e}")
        return []

    def get_occupation_details(self, occupation_code: str) -> Dict:
        if self.api_key and occupation_code:
            try:
                response = requests.get(
                    f"https://services.onetcenter.org/ws/online/occupations/{occupation_code}",
                    auth=self.auth,
                    headers={"Accept": "application/json"},
                    timeout=10,
                )
                if response.status_code == 200:
                    return response.json()
            except Exception as e:
                logger.error(f"ONET API error: {e}")
        return {}