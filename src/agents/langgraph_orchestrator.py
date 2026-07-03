"""Unified Agent Orchestrator using LangGraph."""
import logging
from typing import Dict, Any, Optional
from src.agents.langgraph_resume_agent import ResumeAgent
from src.agents.langgraph_skill_agent import SkillAgent
from src.agents.langgraph_career_agent import CareerAgent
from src.agents.langgraph_learning_agent import LearningAgent
from src.agents.langgraph_market_agent import MarketAgent
from src.agents.langgraph_talent_agent import TalentAgent

logger = logging.getLogger(__name__)


class UnifiedAgentOrchestrator:
    """
    Orchestrates multiple specialized LangGraph agents.
    
    This orchestrator demonstrates true agentic behavior:
    - Each agent has its own reasoning loop (think-act-observe-reflect)
    - Tools are explicitly defined in tool modules
    - Agents communicate through state and results
    - Clear separation of concerns
    """

    def __init__(self, llm_client: Optional[Any] = None, esco_repo=None, onet_repo=None, workbook_repo=None):
        self.llm = llm_client
        
        # Initialize specialized agents
        self.resume_agent = ResumeAgent(llm_client=self.llm, workbook_repo=workbook_repo)
        self.skill_agent = SkillAgent(workbook_repo=workbook_repo, llm_client=self.llm)
        self.career_agent = CareerAgent(esco_repo=esco_repo, llm_client=self.llm)
        self.learning_agent = LearningAgent(esco_repo=esco_repo, llm_client=self.llm)
        self.market_agent = MarketAgent(esco_repo=esco_repo, onet_repo=onet_repo, llm_client=self.llm)
        self.talent_agent = TalentAgent(llm_client=self.llm)
        
        logger.info("[ORCHESTRATOR] Initialized all agents")

    def process_resume_and_analyze(
        self,
        pdf_path: str,
        target_role: Optional[str] = None,
        learning_style: str = "balanced"
    ) -> Dict[str, Any]:
        """
        Complete pipeline: Resume → Skills → Career Path → Learning Roadmap
        
        This demonstrates agents working together in a coordinated workflow.
        """
        logger.info("[ORCHESTRATOR] Starting complete career analysis pipeline")
        logger.info(f"[PIPELINE] Step 1/4: Resume Processing")
        
        # Step 1: Resume Agent - Extract profile
        resume_result = self.resume_agent.process_resume(pdf_path)
        profile = resume_result["extracted_profile"]
        
        if not profile or profile.get("error"):
            raise ValueError(f"Failed to extract resume: {profile.get('error', 'Unknown error')}")
        
        current_role = profile.get("role", "Software Developer")
        current_skills = profile.get("skills", [])
        experience = profile.get("experience", 0)
        education = profile.get("education", [])
        
        logger.info(f"[PIPELINE] Extracted: {current_role}, {len(current_skills)} skills, {experience} years experience")
        
        # Step 2: If no target role specified, use current role
        if not target_role:
            target_role = current_role
        
        logger.info(f"[PIPELINE] Step 2/4: Skill Analysis")
        
        # Step 2: Skill Agent - Analyze readiness
        skill_analysis = self.skill_agent.analyze_skills(
            current_skills,
            target_role,
            user_profile={
                "role": current_role,
                "current_role": current_role,
                "experience_years": experience,
            },
        )
        skill_gaps = list(dict.fromkeys(
            skill_analysis.get("core_gaps", [])
            + [item.get("skill", "") for item in skill_analysis.get("skill_analysis", {}).get("skill_gaps", [])]
        ))
        
        logger.info(f"[PIPELINE] Skills analyzed: {skill_analysis['readiness_summary']['readiness_category']} readiness")
        
        logger.info(f"[PIPELINE] Step 3/4: Career Transition Analysis")
        
        # Step 3: Career Agent - Analyze transition
        career_analysis = self.career_agent.analyze_transition(
            skill_analysis,
            current_skills=current_skills,
            user_profile={
                "current_role": current_role,
                "target_role": target_role,
                "experience_years": experience,
            },
        )
        
        logger.info(f"[PIPELINE] Career transition: {career_analysis['feasibility_analysis']['feasibility']}")
        
        logger.info(f"[PIPELINE] Step 4/4: Learning Roadmap Generation")
        
        # Step 4: Learning Agent - Generate roadmap
        learning_roadmap = self.learning_agent.generate_learning_roadmap(
            skill_gaps,
            current_skills,
            target_role,
            learning_style
        )
        
        logger.info(f"[PIPELINE] Learning roadmap created")
        
        # Aggregate all results
        complete_analysis = {
            "profile": {
                "role": current_role,
                "experience_years": experience,
                "current_skills": current_skills,
                "education": education,
            },
            "skill_analysis": skill_analysis,
            "career_analysis": career_analysis,
            "learning_roadmap": learning_roadmap,
            "pipeline_status": "complete",
        }
        
        logger.info("[PIPELINE] Complete analysis pipeline finished successfully")
        return complete_analysis

    def get_agent_thought_process(self, agent_name: str) -> Optional[list]:
        """Retrieve thought process from a specific agent."""
        agent_map = {
            "resume": self.resume_agent,
            "skill": self.skill_agent,
            "career": self.career_agent,
            "learning": self.learning_agent,
            "market": self.market_agent,
            "talent": self.talent_agent,
        }
        
        agent = agent_map.get(agent_name)
        if agent and hasattr(agent, "last_result"):
            return agent.last_result.get("messages", [])
        return None

    def explain_agent_reasoning(self, analysis: Dict[str, Any]) -> str:
        """Generate human-readable explanation of agent reasoning."""
        explanation = """
        AGENT REASONING PROCESS
        =======================
        
        1. RESUME AGENT - Extracted Profile
        ├─ Role: {}
        ├─ Experience: {} years
        ├─ Skills: {} identified
        └─ Education: {} entries
        
        2. SKILL AGENT - Readiness Assessment
        ├─ Target Role: {}
        ├─ Readiness Level: {}
        ├─ Matched Skills: {}
        ├─ Missing Skills: {}
        └─ Gap Analysis: {}
        
        3. CAREER AGENT - Transition Analysis
        ├─ Feasibility: {}
        ├─ Transition Score: {}%
        ├─ Alternative Paths: {}
        └─ Timeline: {} months
        
        4. LEARNING AGENT - Roadmap Generation
        ├─ Learning Path: {} phases
        ├─ Projects: {}
        ├─ Duration: {} weeks
        └─ Resources: {} platforms
        """.format(
            analysis["profile"]["role"],
            analysis["profile"]["experience_years"],
            len(analysis["profile"]["current_skills"]),
            len(analysis["profile"]["education"]),
            
            analysis["career_analysis"]["feasibility_analysis"]["target_role"],
            analysis["skill_analysis"]["readiness_summary"].get("readiness_category", "N/A"),
            analysis["skill_analysis"]["readiness_summary"].get("readiness_score", 0),
            len(analysis["skill_analysis"].get("core_gaps", [])),
            analysis["skill_analysis"].get("skill_analysis", {}),
            
            analysis["career_analysis"]["feasibility_analysis"]["feasibility"],
            analysis["career_analysis"]["feasibility_analysis"]["transition_score"],
            len(analysis["career_analysis"]["career_path_options"].get("possible_transitions", [])),
            analysis["career_analysis"]["transition_timeline"].get("estimated_months", 0),
            
            len(analysis["learning_roadmap"]["learning_path"].get("phases", {})),
            analysis["learning_roadmap"]["project_roadmap"].get("total_projects", 0),
            analysis["learning_roadmap"]["learning_path"].get("total_estimated_weeks", 0),
            analysis["learning_roadmap"]["learning_resources"].get("resource_count", 0),
        )
        
        return explanation
