"""Career transition and planning tools for LangChain agents."""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CareerTools:
    """Suite of career transition and planning tools."""

    def __init__(self, esco_repo=None):
        self.esco_repo = esco_repo

    def analyze_transition_feasibility(
        self, 
        current_role: str, 
        target_role: str, 
        current_skills: List[str],
        skill_gap_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, any]:
        """
        Analyze feasibility of transitioning from one role to another.
        
        Args:
            current_role: Current job role
            target_role: Desired job role
            current_skills: List of current skills
            skill_gap_context: Optional skill-gap analysis from Skill Agent (preferred)
            
        Returns:
            Feasibility analysis with transition score and requirements
        """
        skill_context = skill_gap_context if skill_gap_context is not None else {}

        if skill_context:
            readiness_score = float(skill_context.get("readiness_summary", {}).get("readiness_score", 0) or 0)
            matched_skills = skill_context.get("skill_analysis", {}).get("matched_skills", []) or []
            skill_gaps = skill_context.get("skill_analysis", {}).get("skill_gaps", []) or []
            missing_core = skill_context.get("skill_analysis", {}).get("missing_core_skills", []) or []
            core_gaps = skill_context.get("core_gaps", []) or []

            total_required = int(skill_context.get("readiness_summary", {}).get("total_skills_required", 0) or 0)
            matched_count = int(skill_context.get("readiness_summary", {}).get("skills_completed", len(matched_skills)) or len(matched_skills))
            missing_count = int(skill_context.get("readiness_summary", {}).get("skills_missing", len(missing_core)) or len(missing_core))
            gap_count = len(skill_gaps)

            transition_score = readiness_score if total_required else round(
                (matched_count / max(1, matched_count + gap_count + missing_count)) * 100, 2
            )

            critical_gaps = []
            for item in skill_gaps:
                skill = item.get("skill") if isinstance(item, dict) else str(item)
                if skill and skill not in critical_gaps:
                    critical_gaps.append(skill)
            for item in missing_core:
                skill = item.get("skill") if isinstance(item, dict) else str(item)
                if skill and skill not in critical_gaps:
                    critical_gaps.append(skill)
            critical_gaps = critical_gaps[:5]

            result = {
                "transition_score": transition_score,
                "current_role": current_role,
                "target_role": target_role,
                "matched_skills_count": matched_count,
                "skills_to_develop": gap_count + missing_count,
                "critical_gaps": critical_gaps,
                "feasibility": "High" if transition_score >= 70 else "Medium" if transition_score >= 40 else "Low",
            }
            logger.info(f"Transition analysis (skill context): {current_role} → {target_role}: {transition_score}% score")
            return result

        return self._analyze_transition_fallback(
            current_role=current_role,
            target_role=target_role,
            current_skills=current_skills,
        )

    def _analyze_transition_fallback(
        self,
        current_role: str,
        target_role: str,
        current_skills: List[str],
    ) -> Dict[str, any]:
        try:
            target_skills = []
            if self.esco_repo:
                try:
                    target_skills = self.esco_repo.get_skills_for_occupation(target_role)
                except Exception as e:
                    logger.warning(f"Could not fetch target skills: {e}")

            current_set = set(s.lower().strip() for s in current_skills if s)
            target_set = set(s.lower().strip() for s in target_skills if s)

            matched = current_set & target_set
            missing = target_set - current_set

            transition_score = round((len(matched) / len(target_set) * 100) if target_set else 0, 2)

            result = {
                "transition_score": transition_score,
                "current_role": current_role,
                "target_role": target_role,
                "matched_skills_count": len(matched),
                "skills_to_develop": len(missing),
                "critical_gaps": sorted(list(missing))[:5] if missing else [],
                "feasibility": "High" if transition_score > 70 else "Medium" if transition_score > 40 else "Low",
                "source": "esco_direct",
            }
            logger.info(f"Transition analysis: {current_role} → {target_role}: {transition_score}% score")
            return result
        except Exception as e:
            logger.error(f"Error analyzing transition: {e}")
            raise

    def identify_career_path_options(
        self, 
        current_role: str, 
        current_skills: List[str]
    ) -> Dict[str, List[str]]:
        """
        Identify possible career path options based on current role and skills.
        
        Args:
            current_role: Current job role
            current_skills: List of current skills
            
        Returns:
            Dictionary with potential career paths
        """
        try:
            # Map skills to potential roles
            role_mappings = {
                'java': ['Senior Java Developer', 'Java Architect', 'Backend Engineer'],
                'python': ['Python Engineer', 'Data Scientist', 'ML Engineer', 'DevOps Engineer'],
                'javascript': ['Frontend Developer', 'Full Stack Developer', 'JavaScript Architect'],
                'react': ['React Developer', 'Frontend Engineer', 'UI Engineer'],
                'docker': ['DevOps Engineer', 'Cloud Engineer', 'Infrastructure Engineer'],
                'kubernetes': ['DevOps Engineer', 'Cloud Architect', 'SRE'],
                'aws': ['Cloud Engineer', 'AWS Solutions Architect', 'Cloud DevOps'],
                'sql': ['Database Administrator', 'Data Engineer', 'Backend Engineer'],
            }
            
            skills_lower = [s.lower() for s in current_skills]
            possible_roles = set()
            
            for skill in skills_lower:
                if skill in role_mappings:
                    possible_roles.update(role_mappings[skill])
            
            result = {
                "current_role": current_role,
                "possible_transitions": sorted(list(possible_roles))[:10],
                "skill_aligned_roles_count": len(possible_roles),
            }
            logger.info(f"Identified {len(possible_roles)} possible career paths from {current_role}")
            return result
        except Exception as e:
            logger.error(f"Error identifying career paths: {e}")
            raise

    def estimate_transition_timeline(
        self, 
        skill_gaps: List[str], 
        current_experience: int
    ) -> Dict[str, any]:
        """
        Estimate how long a career transition would take.
        
        Args:
            skill_gaps: Skills that need to be learned
            current_experience: Years of current experience
            
        Returns:
            Timeline estimate with learning phases
        """
        try:
            # Basic timeline estimation
            gap_count = len(skill_gaps)
            weeks_per_skill = 4  # Assuming 4 weeks per skill on average
            base_weeks = gap_count * weeks_per_skill
            
            # Adjust based on experience
            if current_experience >= 5:
                adjustment = 0.7  # Experienced people learn faster
            elif current_experience >= 3:
                adjustment = 0.85
            else:
                adjustment = 1.0
            
            total_weeks = int(base_weeks * adjustment)
            
            result = {
                "skill_gaps": len(skill_gaps),
                "estimated_weeks": total_weeks,
                "estimated_months": round(total_weeks / 4, 1),
                "timeline_phases": {
                    "foundation": f"Week 1-{total_weeks//3}: Learn fundamentals",
                    "intermediate": f"Week {total_weeks//3}-{2*total_weeks//3}: Build projects",
                    "advanced": f"Week {2*total_weeks//3}-{total_weeks}: Master and specialize",
                },
                "experience_adjustment": f"{adjustment*100:.0f}%",
            }
            logger.info(f"Estimated transition timeline: {total_weeks} weeks")
            return result
        except Exception as e:
            logger.error(f"Error estimating timeline: {e}")
            raise

    def get_tools(self):
        """Return all tools as a list for agent."""
        return [
            self.analyze_transition_feasibility,
            self.identify_career_path_options,
            self.estimate_transition_timeline,
        ]
