import requests
import logging
from typing import Dict, Any, List, Optional
import json
import os
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

class ESCORepository:
    BASE_URL = "https://ec.europa.eu/esco/api"
    
    def __init__(self, cache_dir: str = "./cache", role_skill_map: Optional[Dict[str, List[str]]] = None, default_skills: Optional[List[str]] = None):
        self.cache_dir = cache_dir
        self.role_skill_map = role_skill_map or {}
        self.default_skills = [skill.strip().lower() for skill in (default_skills or ["python", "java", "sql", "docker", "git"]) if skill.strip()]
        os.makedirs(cache_dir, exist_ok=True)

    def _get_cached(self, cache_key: str) -> Optional[Dict]:
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return None

    def _set_cache(self, cache_key: str, data: Dict):
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.json")
        try:
            with open(cache_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning(f"Cache write failed: {e}")

    def _is_relevant_skill(self, skill_text: str) -> bool:
        """Check if skill is relevant for tech roles"""
        tech_indicators = ["programming", "java", "python", "javascript", "sql", "database", 
                          "docker", "kubernetes", "aws", "cloud", "spring", "git", "api", "rest",
                          "testing", "debugging", "frontend", "backend", "framework"]
        skill_lower = skill_text.lower()
        return any(indicator in skill_lower for indicator in tech_indicators)

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(str(value).lower().strip().split())

    @staticmethod
    def _tokenize(value: str) -> List[str]:
        normalized = ESCORepository._normalize_text(value)
        tokens = [token.strip(".,:/()[]{}") for token in normalized.split()]
        return [token for token in tokens if token]

    @staticmethod
    def _specific_tokens(value: str) -> List[str]:
        generic_tokens = {
            "senior", "junior", "lead", "principal", "staff", "engineer", "developer",
            "specialist", "expert", "manager", "associate", "architect",
        }
        tokens = ESCORepository._tokenize(value)
        specific = [token for token in tokens if token not in generic_tokens]
        return specific or tokens

    def _occupation_score(self, occupation: Dict[str, Any], target_role: str) -> float:
        target = self._normalize_text(target_role)
        preferred = occupation.get("preferredLabel") or {}
        title = preferred.get("en") or preferred.get("en-us") or occupation.get("title") or ""
        title_normalized = self._normalize_text(title)
        search_hit = self._normalize_text(occupation.get("searchHit", ""))

        ratio = SequenceMatcher(None, target, title_normalized).ratio()
        target_tokens = set(self._specific_tokens(target))
        title_tokens = set(self._tokenize(title_normalized))
        overlap = len(target_tokens & title_tokens)
        overlap_ratio = overlap / max(1, len(target_tokens))

        score = ratio + (1.6 * overlap_ratio)
        if target and target in title_normalized:
            score += 1.0
        if overlap and all(token in title_tokens for token in target_tokens):
            score += 1.0
        if target and target in search_hit:
            score += 0.4

        software_markers = {"software", "backend", "frontend", "fullstack", "full-stack", "web", "application"}
        unrelated_for_software = {
            "satellite", "aerospace", "industrial", "mineral", "electrical", "optoelectronic",
            "mechatronics", "microsystem", "ship", "marine", "mechanical",
        }
        target_is_software = bool(set(self._tokenize(target)) & software_markers)
        if target_is_software:
            if title_tokens & software_markers:
                score += 1.2
            if title_tokens & unrelated_for_software:
                score -= 1.5

        return score

    def _best_occupation_match(self, occupation_name: str, occupations: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not occupations:
            return None
        scored = sorted(
            occupations,
            key=lambda item: self._occupation_score(item, occupation_name),
            reverse=True,
        )
        best = scored[0]
        if self._occupation_score(best, occupation_name) < 0.25:
            return None
        return best

    def search_skill(self, skill_name: str) -> List[Dict]:
        cache_key = f"skill_search_{skill_name.lower().replace(' ', '_')}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        try:
            response = requests.get(
                f"{self.BASE_URL}/search",
                params={"text": skill_name, "type": "skill", "language": "en"},
                headers={"Accept": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
            results = response.json()
            skills = results.get("_embedded", {}).get("results", [])
            self._set_cache(cache_key, skills)
            return skills
        except Exception as e:
            logger.error(f"ESCO skill search failed: {e}")
            return []

    def search_occupation(self, occupation_name: str) -> List[Dict]:
        cache_key = f"occupation_search_{occupation_name.lower().replace(' ', '_')}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        try:
            response = requests.get(
                f"{self.BASE_URL}/search",
                params={"text": occupation_name, "type": "occupation", "language": "en"},
                headers={"Accept": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
            results = response.json()
            occupations = results.get("_embedded", {}).get("results", [])
            self._set_cache(cache_key, occupations)
            return occupations
        except Exception as e:
            logger.error(f"ESCO occupation search failed: {e}")
            return []

    def get_occupation_details(self, occupation_uri: str) -> Dict[str, Any]:
        if not occupation_uri:
            return {}
        cache_key = f"occupation_{occupation_uri.replace(':', '_').replace('/', '_')}"
        cached = self._get_cached(cache_key)
        if isinstance(cached, dict):
            return cached
        try:
            response = requests.get(
                f"{self.BASE_URL}/resource/occupation",
                params={"uri": occupation_uri, "language": "en"},
                headers={"Accept": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
            details = response.json()
            if isinstance(details, dict):
                self._set_cache(cache_key, details)
                return details
        except Exception as e:
            logger.error(f"ESCO occupation details failed: {e}")
        return {}

    @staticmethod
    def _extract_skill_titles_from_occupation(details: Dict[str, Any]) -> List[str]:
        links = details.get("_links", {}) if isinstance(details, dict) else {}
        titles: List[str] = []
        for key in ("hasEssentialSkill", "hasOptionalSkill"):
            for link in links.get(key, []) or []:
                title = str(link.get("title", "")).strip().lower()
                if title:
                    titles.append(title)
        unique_titles: List[str] = []
        seen = set()
        for title in titles:
            if title not in seen:
                seen.add(title)
                unique_titles.append(title)
        return unique_titles

    def get_skills_for_occupation(self, occupation_label: str) -> List[str]:
        return self.get_skill_lookup_result(occupation_label)["skills"]

    def get_skill_lookup_result(self, occupation_label: str) -> Dict[str, Any]:
        """Get occupation skills from ESCO API first, then fall back to configured maps/defaults."""
        role_lower = self._normalize_text(occupation_label)

        # 1) Live ESCO retrieval from best occupation match.
        occupations = self.search_occupation(occupation_label)
        best_occupation = self._best_occupation_match(occupation_label, occupations)
        if best_occupation:
            occupation_uri = str(best_occupation.get("uri", "")).strip()
            details = self.get_occupation_details(occupation_uri)
            extracted = self._extract_skill_titles_from_occupation(details)
            if extracted:
                logger.info(
                    "Retrieved %s ESCO skills from occupation resource for role '%s'",
                    len(extracted),
                    occupation_label,
                )
                return {
                    "skills": extracted,
                    "source": "esco_live",
                    "live": True,
                }

        # 2) Configurable role map fallback.
        for role_key, keywords in self.role_skill_map.items():
            if role_key in role_lower or any(word in role_lower for word in role_key.split()):
                mapped = [kw.strip().lower() for kw in keywords if str(kw).strip()]
                if mapped:
                    logger.info("Using ESCO role-skill map fallback for role '%s'", occupation_label)
                    return {
                        "skills": mapped,
                        "source": "esco_role_map",
                        "live": False,
                    }

        # 3) Default fallback.
        logger.info("Using ESCO default skill fallback for role '%s'", occupation_label)
        return {
            "skills": [skill for skill in self.default_skills if skill],
            "source": "esco_default",
            "live": False,
        }

    def get_related_skills(self, skill_name: str) -> List[str]:
        skills = self.search_skill(skill_name)
        if not skills:
            return []
        skill_uri = skills[0].get("uri", "")
        if not skill_uri:
            return []
        try:
            response = requests.get(
                f"{self.BASE_URL}/resource/skill",
                params={"uri": skill_uri},
                headers={"Accept": "application/json"},
                timeout=10,
            )
            if response.status_code == 200:
                details = response.json()
                related = details.get("relatedSkills", [])
                return [s.get("label", {}).get("en", "").lower() for s in related if s.get("label")]
        except Exception as e:
            logger.error(f"ESCO skill details failed: {e}")
        return []