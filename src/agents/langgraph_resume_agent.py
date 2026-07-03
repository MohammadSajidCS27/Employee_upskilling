"""Resume Agent using LangGraph and LangChain."""
import logging
from typing import TypedDict, List, Optional, Any
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from src.tools.resume_tools import ResumeTools
from src.models.resume_schema import ResumeProfileSchema

logger = logging.getLogger(__name__)


class ResumeAgentState(TypedDict):
    """State for resume extraction agent."""
    pdf_path: str
    resume_text: str
    extracted_profile: dict
    role: Optional[str]
    experience: Optional[int]
    skills: List[str]
    education: List[str]
    messages: List[BaseMessage]
    current_step: str
    error: Optional[str]


class ResumeAgent:
    """Resume extraction agent using LangGraph."""

    def __init__(self, llm_client: Optional[Any] = None, workbook_repo: Optional[Any] = None):
        self.llm = llm_client
        self.tools = ResumeTools(workbook_repo=workbook_repo)
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph state machine."""
        graph = StateGraph(ResumeAgentState)

        # Define nodes (actions)
        graph.add_node("extract_text", self._extract_text_node)
        graph.add_node("extract_role", self._extract_role_node)
        graph.add_node("extract_experience", self._extract_experience_node)
        graph.add_node("extract_skills", self._extract_skills_node)
        graph.add_node("extract_education", self._extract_education_node)
        graph.add_node("normalize_and_return", self._normalize_node)
        graph.add_node("error_handler", self._error_handler_node)

        # Define edges (transitions)
        graph.set_entry_point("extract_text")
        graph.add_edge("extract_text", "extract_role")
        graph.add_edge("extract_role", "extract_experience")
        graph.add_edge("extract_experience", "extract_skills")
        graph.add_edge("extract_skills", "extract_education")
        graph.add_edge("extract_education", "normalize_and_return")
        graph.add_edge("normalize_and_return", END)

        return graph.compile()

    def _extract_text_node(self, state: ResumeAgentState) -> dict:
        """Node: Extract text from PDF."""
        logger.info(f"[AGENT] Step: Extract text from {state['pdf_path']}")
        try:
            text = self.tools.extract_text_from_pdf(state["pdf_path"])
            state["resume_text"] = text
            state["current_step"] = "extract_text"
            state["messages"].append(
                AIMessage(content=f"✓ Extracted {len(text)} characters from PDF")
            )
            logger.info(f"[AGENT] Extracted {len(text)} characters")
            return state
        except Exception as e:
            state["error"] = str(e)
            logger.error(f"[AGENT] Error extracting text: {e}")
            raise

    def _extract_role_node(self, state: ResumeAgentState) -> dict:
        """Node: Extract job role."""
        logger.info("[AGENT] Step: Extract job role")
        try:
            role = self.tools.extract_role_from_resume(state["resume_text"])
            state["role"] = role
            state["current_step"] = "extract_role"
            state["messages"].append(AIMessage(content=f"✓ Extracted role: {role}"))
            logger.info(f"[AGENT] Extracted role: {role}")
            return state
        except Exception as e:
            state["error"] = str(e)
            logger.error(f"[AGENT] Error extracting role: {e}")
            raise

    def _extract_experience_node(self, state: ResumeAgentState) -> dict:
        """Node: Extract years of experience."""
        logger.info("[AGENT] Step: Extract experience")
        try:
            experience = self.tools.extract_experience_from_resume(state["resume_text"])
            state["experience"] = experience
            state["current_step"] = "extract_experience"
            state["messages"].append(AIMessage(content=f"✓ Extracted experience: {experience} years"))
            logger.info(f"[AGENT] Extracted experience: {experience} years")
            return state
        except Exception as e:
            state["error"] = str(e)
            logger.error(f"[AGENT] Error extracting experience: {e}")
            raise

    def _extract_skills_node(self, state: ResumeAgentState) -> dict:
        """Node: Extract technical skills."""
        logger.info("[AGENT] Step: Extract skills")
        try:
            skills = self.tools.extract_skills_from_resume(state["resume_text"])
            state["skills"] = skills
            state["current_step"] = "extract_skills"
            state["messages"].append(AIMessage(content=f"✓ Extracted {len(skills)} skills: {', '.join(skills[:5])}..."))
            logger.info(f"[AGENT] Extracted {len(skills)} skills")
            return state
        except Exception as e:
            state["error"] = str(e)
            logger.error(f"[AGENT] Error extracting skills: {e}")
            raise

    def _extract_education_node(self, state: ResumeAgentState) -> dict:
        """Node: Extract education background."""
        logger.info("[AGENT] Step: Extract education")
        try:
            education = self.tools.extract_education_from_resume(state["resume_text"])
            state["education"] = education
            state["current_step"] = "extract_education"
            state["messages"].append(
                AIMessage(content=f"✓ Extracted {len(education)} education entries")
            )
            logger.info(f"[AGENT] Extracted {len(education)} education entries")
            return state
        except Exception as e:
            state["error"] = str(e)
            logger.error(f"[AGENT] Error extracting education: {e}")
            raise

    def _normalize_node(self, state: ResumeAgentState) -> dict:
        """Node: Normalize and finalize profile."""
        logger.info("[AGENT] Step: Normalize profile")
        try:
            normalized_skills = self.tools.normalize_skills(state["skills"])
            state["skills"] = normalized_skills
            
            profile = {
                "role": state["role"],
                "experience": state["experience"],
                "skills": normalized_skills,
                "education": state["education"],
            }
            validated = ResumeProfileSchema.model_validate(profile)
            state["extracted_profile"] = validated.model_dump()
            state["current_step"] = "normalize"
            state["messages"].append(AIMessage(content="✓ Profile extracted and normalized"))
            logger.info("[AGENT] Profile normalized and complete")
            return state
        except Exception as e:
            state["error"] = str(e)
            logger.error(f"[AGENT] Error normalizing: {e}")
            raise

    def _error_handler_node(self, state: ResumeAgentState) -> dict:
        """Node: Handle errors."""
        logger.error(f"[AGENT] Error: {state['error']}")
        state["messages"].append(
            AIMessage(content=f"✗ Error: {state['error']}")
        )
        return state

    def process_resume(self, pdf_path: str) -> dict:
        """Process resume and extract profile."""
        initial_state = ResumeAgentState(
            pdf_path=pdf_path,
            resume_text="",
            extracted_profile={},
            role=None,
            experience=None,
            skills=[],
            education=[],
            messages=[HumanMessage(content=f"Process resume from {pdf_path}")],
            current_step="",
            error=None,
        )

        logger.info("[AGENT] Starting resume processing...")
        result = self.graph.invoke(initial_state)
        
        logger.info(f"[AGENT] Resume processing complete: {result['extracted_profile']}")
        return result
