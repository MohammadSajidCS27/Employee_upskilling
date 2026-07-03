import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class SkillNormalizer:
    def __init__(self, mappings: Optional[Dict[str, str]] = None, synonyms: Optional[Dict[str, List[str]]] = None):
        # Load from config/database if available, otherwise use defaults
        self.skill_mappings = mappings or self._load_default_mappings()
        self.synonym_map = synonyms or self._load_default_synonyms()
        self._loaded_from_config = mappings is not None

    def _load_default_mappings(self) -> Dict[str, str]:
        """Default mappings - used only as fallback"""
        return {
            "js": "javascript",
            "ts": "typescript",
            "k8s": "kubernetes",
            "postgres": "postgresql",
            "mongo": "mongodb",
            "gcp": "google cloud platform",
            "ml": "machine learning",
            "ai": "artificial intelligence",
            "ci cd": "ci/cd",
            "cicd": "ci/cd",
            "continuous integration": "ci/cd",
            "continuous deployment": "ci/cd",
            "gitlab ci": "ci/cd",
            "api security": "security",
            "service mesh security": "service mesh",
            "html5": "html",
            "css3": "css",
            "nextjs": "next.js",
            "next js": "next.js",
            "tailwindcss": "tailwind",
        }

    def _load_default_synonyms(self) -> Dict[str, List[str]]:
        return {
            "python": ["python3", "python2"],
            "java": ["java8", "java11", "java17", "java21"],
            "docker": ["docker compose", "containerization"],
            "aws": ["ec2", "s3", "lambda", "cloudformation"],
            "ci/cd": ["jenkins", "gitlab ci", "continuous integration", "continuous deployment"],
            "security": ["api security", "auth", "authentication", "authorization"],
            "service mesh": ["istio", "linkerd", "service mesh security"],
            "testing": ["jest", "mocha", "cypress", "selenium", "unit testing", "e2e testing", "end-to-end testing"],
            "version control": ["git", "github", "gitlab", "bitbucket"],
            "build tools": ["webpack", "babel", "gulp", "grunt", "npm", "yarn"],
            "frontend frameworks": ["react", "angular", "vue", "react.js", "vue.js", "angular.js"],
            "ui/ux design": ["figma", "sketch", "prototyping", "user research", "wireframing"],
            "agile": ["scrum", "kanban", "jira", "confluence"],
            "communication": ["teamwork", "collaboration", "stakeholder management"],
            "task runners": ["gulp", "grunt", "npm scripts"],
            "micro frontend": ["microfrontend", "micro-frontend"],
        }

    def normalize(self, skill: str) -> str:
        skill_lower = skill.lower().strip()
        return self.skill_mappings.get(skill_lower, skill_lower)

    def normalize_list(self, skills: List[str]) -> List[str]:
        normalized: List[str] = []
        for skill in skills:
            value = str(skill or "").strip()
            if not value:
                continue

            # Split explicit multi-skill strings while preserving meaningful terms.
            parts = re.split(r",|/|\||\band\b", value, flags=re.IGNORECASE)
            for part in parts:
                candidate = part.strip()
                if not candidate:
                    continue
                normalized.append(self.normalize(candidate))

        # Preserve order and remove duplicates.
        deduped: List[str] = []
        seen = set()
        for item in normalized:
            key = item.lower().strip()
            if key and key not in seen:
                seen.add(key)
                deduped.append(key)
        return deduped

    def get_similar_skills(self, skill: str) -> List[str]:
        return self.synonym_map.get(skill.lower(), [])