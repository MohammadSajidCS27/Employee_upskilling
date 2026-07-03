"""Skill analysis tools for LangChain agents."""
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SkillTools:
    """Suite of skill analysis tools."""

    def __init__(self, workbook_repo=None, llm_client=None):
        self.workbook_repo = workbook_repo
        self.llm_client = llm_client
        from src.services.skill_normalizer import SkillNormalizer
        self.skill_normalizer = SkillNormalizer()

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(str(value or "").lower().strip().split())

    @staticmethod
    def _tokenize(value: str) -> List[str]:
        normalized = SkillTools._normalize_text(value)
        tokens = [token.strip(".,:/()[]{}") for token in normalized.split()]
        result = []
        for token in tokens:
            for part in token.replace("/", " ").replace(".", " ").replace("&", " ").replace("-", " ").split():
                cleaned = part.strip(".,:/()[]{}")
                if cleaned:
                    result.append(cleaned)
        return result

    @staticmethod
    def _unique(values: List[str]) -> List[str]:
        ordered: List[str] = []
        seen = set()
        for value in values:
            cleaned = str(value or "").strip().lower()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                ordered.append(cleaned)
        return ordered

    def _is_relevant_skill(self, skill: str, role: str) -> bool:
        skill_tokens = set(self._tokenize(skill))
        role_tokens = set(self._tokenize(role))
        if not skill_tokens:
            return False
        if skill_tokens & role_tokens:
            return True

        tech_tokens = {
            "java", "python", "javascript", "typescript", "spring", "boot", "django", "flask", "fastapi",
            "react", "angular", "node", "sql", "postgresql", "mongodb", "redis", "docker", "kubernetes",
            "aws", "azure", "gcp", "api", "rest", "microservices", "git", "ci", "cd", "devops", "cloud",
            "backend", "frontend", "security", "testing", "pytest", "jenkins", "terraform", "linux",
            "software", "programming", "development",             "frontend", "front", "back", "end",
            "framework", "frameworks", "library", "database",
            "html", "css", "sass", "less", "bootstrap", "tailwind", "vue", "jquery", "responsive",
            "web", "ui", "ux", "figma", "accessibility", "cross-browser", "performance",
            "css3", "flexbox", "grid", "scss", "webpack", "babel", "gulp", "grunt", "npm", "yarn",
            "redux", "ngrx", "vuex", "jest", "mocha", "cypress", "selenium", "jmeter",
            "material", "ant", "design", "wireframe", "prototype", "wcag", "xss", "csp",
            "optimization", "lazy", "minification", "compression", "image",
            "es6", "es7", "esnext", "js", "version", "control", "github", "gitlab", "bitbucket",
            "authentication", "authorization", "oauth", "jwt", "sso", "oauth2",
            "agile", "scrum", "kanban", "jira", "confluence",
            "communication", "teamwork", "leadership", "collaboration",
            "golang", "rust", "swift", "kotlin", "flutter", "react-native",
            "next", "nextjs", "nuxt", "svelte",
            "typescript", "javascript", "jsx", "tsx",
            "tailwindcss", "bootstrap", "foundation",
            "jest", "vitest", "testing-library",
            "docker", "podman", "containerd",
            "helm", "istio", "linkerd",
            "grafana", "prometheus", "datadog", "newrelic",
            "graphql", "apollo", "relay",
            "sass", "scss", "less", "stylus",
            "babel", "swc", "esbuild", "vite",
            "gulp", "grunt", "webpack", "rollup", "parcel",
            "npm", "yarn", "pnpm", "bun",
            "git", "github", "gitlab", "bitbucket", "svn",
            "jira", "confluence", "notion", "asana", "trello",
            "figma", "sketch", "adobe", "photoshop", "illustrator",
            "wcag", "section508", "a11y",
            "seo", "sem", "analytics", "gtm",
            "pwa", "spa", "ssr", "ssg",
            "a11y", "i18n", "l10n",
            "features", "task", "runners", "taskrunners",
            "team", "people", "stakeholder",
            "micro", "frontend", "microfrontend",
            "csp", "xss", "csrf", "security",
            "lazy", "loading", "code", "splitting",
            "minification", "compression", "brotli", "gzip",
            "image", "images", "optimization", "webp", "avif",
            "cross", "browser", "compatibility",
            "user", "centered", "design",
            "prototyping", "tools",
            "collaboration", "communication",
        }

        software_role_markers = {"software", "backend", "frontend", "fullstack", "full-stack", "web", "application"}
        software_role = bool(role_tokens & software_role_markers)

        banned_for_software = {
            "satellite", "satellites", "aerospace", "industrial", "mechanical", "electrical", "mineral",
            "marine", "ship", "drawing", "drafting", "cad", "civil", "manufacturing",
        }
        if software_role and skill_tokens & banned_for_software:
            return False

        if skill_tokens & tech_tokens:
            return True

        unrelated_domains = {
            "satellite", "satellites", "aerospace", "aviation", "maritime", "nursing", "pharmacy",
            "veterinary", "geology", "astronomy", "spacecraft",
        }
        if skill_tokens & unrelated_domains:
            return False

        return len(skill_tokens & role_tokens) > 0

    def get_expected_skills_for_role(self, role: str) -> List[str]:
        """
        Get expected skills for a job role from ESCO repository.
        
        Args:
            role: Job role title (e.g., "Java Developer", "Data Scientist")
            
        Returns:
            List of expected skills for the role
        """
        try:
            lookup = self.get_expected_skill_lookup(role)
            return lookup.get("skills", [])
        except Exception as e:
            logger.error(f"Error getting expected skills: {e}")
            raise

    def get_expected_skill_lookup(self, role: str, experience_years: int = 0, current_skills: Optional[List[str]] = None) -> Dict[str, Any]:
        """Get expected skills and lookup metadata from configured repositories."""
        role_value = str(role or "").strip()

        if self.workbook_repo and hasattr(self.workbook_repo, "get_all_skills_for_role"):
            try:
                workbook = self.workbook_repo.get_all_skills_for_role(role_value, experience_years=experience_years, current_skills=current_skills)
            except TypeError:
                try:
                    workbook = self.workbook_repo.get_all_skills_for_role(role_value, experience_years=experience_years)
                except TypeError:
                    workbook = self.workbook_repo.get_all_skills_for_role(role_value)
            if isinstance(workbook, dict):
                workbook_skills = self._unique(workbook.get("skills", []))
                # Return ALL skills from the matched sheet without filtering
                if workbook_skills:
                    logger.info(
                        "Skill lookup for '%s' via workbook all_skheets source=%s count=%s",
                        role_value,
                        workbook.get("source", "workbook"),
                        len(workbook_skills),
                    )
                    return {
                        "skills": workbook_skills,
                        "source": workbook.get("source", "workbook"),
                        "live": False,
                        "provider": "workbook",
                        "sheet": workbook.get("sheet"),
                        "workbook_file": workbook.get("workbook_file", ""),
                        "experience_bucket": workbook.get("experience_bucket"),
                        "skill_levels": workbook.get("skill_levels", {}),
                        "headings": workbook.get("headings", {}),
                    }

        if self.workbook_repo and hasattr(self.workbook_repo, "get_skill_lookup_result"):
            try:
                workbook = self.workbook_repo.get_skill_lookup_result(role_value, experience_years=experience_years, current_skills=current_skills)
            except TypeError:
                try:
                    workbook = self.workbook_repo.get_skill_lookup_result(role_value, experience_years=experience_years)
                except TypeError:
                    workbook = self.workbook_repo.get_skill_lookup_result(role_value)
            if isinstance(workbook, dict):
                workbook_skills = self._unique(workbook.get("skills", []))
                workbook_relevant = workbook_skills
                if not workbook_relevant:
                    workbook_relevant = [
                        skill for skill in workbook_skills if self._is_relevant_skill(skill, role_value)
                    ]
                if workbook_relevant:
                    logger.info(
                        "Skill lookup for '%s' via workbook source=%s count=%s",
                        role_value,
                        workbook.get("source", "workbook"),
                        len(workbook_relevant),
                    )
                    return {
                        "skills": workbook_relevant,
                        "source": workbook.get("source", "workbook"),
                        "live": False,
                        "provider": "workbook",
                        "sheet": workbook.get("sheet"),
                        "workbook_file": workbook.get("workbook_file", ""),
                        "experience_bucket": workbook.get("experience_bucket"),
                        "skill_levels": workbook.get("skill_levels", {}),
                        "headings": workbook.get("headings", {}),
                    }

        # No workbook match: fall back to LLM-generated skills, then empty.
        llm_lookup = self._llm_skill_lookup(role_value)
        if llm_lookup.get("skills"):
            logger.info("Skill lookup for '%s' via LLM fallback count=%s", role_value, len(llm_lookup["skills"]))
            return llm_lookup

        logger.warning("No skill source available for role '%s' (workbook empty, LLM unavailable)", role_value)
        return {
            "skills": [],
            "source": "unavailable",
            "live": False,
            "provider": "none",
            "skill_levels": {},
        }

    def _llm_skill_lookup(self, role_value: str) -> Dict[str, Any]:
        """Generate expected skills for a role via the LLM when the workbook has no match.

        Acts as an objective senior skill-gap analyst: returns the skills genuinely
        essential to the role (independent of any candidate), each with a required
        proficiency level (1-4) and a category, so gaps stay grounded and unbiased.
        """
        if not self.llm_client or not role_value:
            return {"skills": [], "source": "llm_unavailable", "live": False, "provider": "llm", "skill_levels": {}, "headings": {}}

        prompt = (
            "You are a senior skill-gap analyst. Define the objective, role-essential skill profile "
            f"for the role '{role_value}'. Judge only by what the role itself requires; do not assume any "
            "specific candidate, and do not invent vague, generic, or unrelated skills. If the role is "
            "unfamiliar, infer the closest standard industry definition rather than guessing. "
            "Return ONLY valid JSON with this shape: "
            "{\"skills\": [{\"name\": \"<lowercase skill>\", \"level\": <1-4>, \"category\": \"<group>\"}]}. "
            "Level scale: 1=awareness, 2=working, 3=proficient, 4=expert. Provide 10-20 truly required skills; "
            "omit any you are unsure about."
        )
        try:
            response = self.llm_client.invoke(prompt)
            content = getattr(response, "content", str(response))
            start = content.find("{")
            end = content.rfind("}")
            if start == -1 or end == -1:
                raise ValueError("no JSON object in LLM response")
            data = json.loads(content[start : end + 1])
            raw_skills = data.get("skills", []) if isinstance(data, dict) else []

            skills: List[str] = []
            skill_levels: Dict[str, int] = {}
            headings: Dict[str, List[str]] = {}
            for item in raw_skills:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip().lower()
                if not name:
                    continue
                level = item.get("level", 3)
                try:
                    level = max(1, min(int(level), 4))
                except (TypeError, ValueError):
                    level = 3
                category = str(item.get("category", "general")).strip().lower() or "general"
                skills.append(name)
                skill_levels[name] = level
                headings.setdefault(category, []).append(name)

            return {
                "skills": self._unique(skills),
                "source": "llm_generated",
                "live": False,
                "provider": "llm",
                "skill_levels": skill_levels,
                "headings": headings,
            }
        except Exception as error:
            logger.warning("LLM skill lookup failed for '%s': %s", role_value, error)
            return {"skills": [], "source": "llm_error", "live": False, "provider": "llm", "skill_levels": {}, "headings": {}}

    def find_skill_gaps(self, current_skills: List[str], expected_skills: List[str]) -> Dict[str, List[str]]:
        """
        Find the gap between current skills and expected skills.
        
        Args:
            current_skills: List of skills the person has
            expected_skills: List of skills needed for the role
            
        Returns:
            Dictionary with 'matched' and 'missing' skill lists
        """
        try:
            current_set = set(s.lower().strip() for s in current_skills if s)
            expected_set = set(s.lower().strip() for s in expected_skills if s)
            
            matched = set()
            missing = set()
            
            for expected in expected_set:
                expected_tokens = set(self._tokenize(expected))
                best_match = None
                best_overlap = 0
                
                for current in current_set:
                    current_tokens = set(self._tokenize(current))
                    overlap = len(expected_tokens & current_tokens)
                    
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_match = current
                
                if best_overlap > 0:
                    matched.add(expected)
                else:
                    missing.add(expected)
            
            result = {
                "matched_skills": sorted(list(matched)),
                "missing_skills": sorted(list(missing)),
                "readiness_score": round((len(matched) / len(expected_set) * 100) if expected_set else 0, 2),
            }
            logger.info(f"Gap analysis: {len(matched)} matched, {len(missing)} missing")
            return result
        except Exception as e:
            logger.error(f"Error finding skill gaps: {e}")
            raise

    def rank_skills_by_importance(self, skills: List[str], role: str) -> Dict[str, List[str]]:
        """
        Rank skills by importance for a specific role.
        
        Args:
            skills: List of skills to rank
            role: Target role
            
        Returns:
            Dictionary with ranked skill categories
        """
        try:
            normalized = [str(skill).strip().lower() for skill in skills if str(skill).strip()]
            # Data-driven default: treat observed role/profile skills as core inputs.
            core_skills = normalized
            soft_skills: List[str] = []
            
            result = {
                "core_technical": core_skills,
                "soft_skills": soft_skills,
                "total_skills": len(normalized),
                "core_count": len(core_skills),
            }
            logger.info(f"Ranked {len(normalized)} skills for {role}")
            return result
        except Exception as e:
            logger.error(f"Error ranking skills: {e}")
            raise

    def get_tools(self):
        """Return all tools as a list for agent."""
        return [
            self.get_expected_skills_for_role,
            self.find_skill_gaps,
            self.rank_skills_by_importance,
        ]
