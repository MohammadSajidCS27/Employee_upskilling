from src.agents.langgraph_resume_agent import ResumeAgent
from src.agents.langgraph_skill_agent import SkillAgent
from src.agents.langgraph_career_agent import CareerAgent
from src.agents.langgraph_learning_agent import LearningAgent
from src.agents.langgraph_market_agent import MarketAgent
from src.agents.langgraph_talent_agent import TalentAgent
from src.models.resume_schema import ResumeProfileSchema
from src.models.market_schema import MarketAgentOutputSchema
from src.models.career_schema import CareerAgentOutputSchema
from src.models.roadmap_schema import RoadmapOutputSchema
from src.tools.resume_tools import ResumeTools


class _FakeLLM:
    def invoke(self, prompt: str):
        class _Resp:
            content = "{\"skills\": []}"
        return _Resp()


class _FakeESCORepo:
    def get_skill_lookup_result(self, role: str, experience_years: int = 0, current_skills=None):
        role_lower = role.lower().strip()
        if role_lower == "ai engineer":
            skills = ["python", "docker", "machine learning", "kubernetes"]
        else:
            skills = ["python", "docker"]
        return {"skills": skills, "source": "workbook", "live": False, "provider": "workbook"}


def test_resume_agent_profile_extraction_from_text():
    agent = ResumeAgent(llm_client=_FakeLLM())
    text = """
    Senior Software Engineer
    Experience: 5 years
    Skills: Python, Java, Docker
    Education: Bachelor of Science in Computer Science
    """

    role = agent.tools.extract_role_from_resume(text)
    experience = agent.tools.extract_experience_from_resume(text)
    skills = agent.tools.extract_skills_from_resume(text)
    education = agent.tools.extract_education_from_resume(text)

    assert role in {"Senior Software Engineer", "Software Engineer", "Software Developer"}
    assert experience == 5
    assert "python" in skills
    assert "docker" in skills
    assert any("bachelor" in item.lower() for item in education)


def test_resume_agent_process_resume_output_schema(monkeypatch):
    agent = ResumeAgent(llm_client=_FakeLLM())

    sample_text = (
        "Senior Software Engineer\n"
        "Experience: 5 years\n"
        "Skills: Python, Java, Docker\n"
        "Education: Bachelor of Science in Computer Science"
    )

    monkeypatch.setattr(agent.tools, "extract_text_from_pdf", lambda _path: sample_text)

    result = agent.process_resume("dummy.pdf")
    profile = ResumeProfileSchema.model_validate(result["extracted_profile"]).model_dump()

    assert result["current_step"] == "normalize"
    assert result["error"] is None
    assert set(profile.keys()) == {"role", "experience", "skills", "education"}
    assert isinstance(profile["skills"], list)


def test_skill_agent_returns_readiness_and_gaps():
    agent = SkillAgent(workbook_repo=_FakeESCORepo(), llm_client=_FakeLLM())
    result = agent.analyze_skills(["python", "docker"], "AI Engineer")

    assert "user_profile" in result
    assert "readiness_summary" in result
    assert "skill_analysis" in result
    assert "skill_dependencies" in result
    assert "core_gaps" in result
    assert "recommendations" in result
    assert result["readiness_summary"]["readiness_score"] >= 0
    assert "machine learning" in result["core_gaps"]


def test_skill_agent_matches_skill_gap_schema_top_level():
    agent = SkillAgent(workbook_repo=_FakeESCORepo(), llm_client=_FakeLLM())
    result = agent.analyze_skills(["python", "docker"], "AI Engineer")

    required_top_keys = {
        "user_profile",
        "readiness_summary",
        "skill_analysis",
        "skill_dependencies",
        "core_gaps",
        "skill_source",
        "recommendations",
    }
    assert required_top_keys.issubset(set(result.keys()))
    assert {"provider", "source", "live"}.issubset(set(result["skill_source"].keys()))


def test_skill_agent_uses_non_live_role_map_skills():
    class _FakeRoleMapRepo:
        def get_skill_lookup_result(self, role: str):
            return {
                "skills": ["java", "spring", "git"],
                "source": "esco_role_map",
                "live": False,
                "provider": "esco",
            }

    agent = SkillAgent(workbook_repo=_FakeRoleMapRepo(), llm_client=_FakeLLM())
    result = agent.analyze_skills(
        ["java"],
        "Java Backend Developer",
        user_profile={
            "employee_id": "EMP001",
            "name": "John Smith",
            "current_role": "Junior Developer",
            "target_role": "Java Backend Developer",
            "experience_years": 2,
        },
    )

    assert result["readiness_summary"]["total_skills_required"] == 3
    assert "spring" in result["core_gaps"]
    assert "git" in result["core_gaps"]


def test_career_agent_transition_analysis_shape():
    agent = CareerAgent(esco_repo=_FakeESCORepo(), llm_client=_FakeLLM())
    skill_gap_context = {
        "user_profile": {
            "current_role": "Software Engineer",
            "target_role": "AI Engineer",
            "experience_years": 4,
        },
        "readiness_summary": {
            "readiness_score": 62.5,
            "readiness_category": "transition_ready",
            "readiness_message": "Can transition with focused learning",
            "total_skills_required": 4,
            "skills_completed": 2,
            "skills_partial": 1,
            "skills_missing": 1,
        },
        "skill_analysis": {
            "matched_skills": ["python", "docker"],
            "skill_gaps": [],
            "missing_core_skills": [{"skill": "machine learning", "priority": "critical"}],
            "missing_optional_skills": [],
            "priority_skills": [{"skill": "machine learning", "priority_rank": 1, "priority": "critical", "gap": 4, "category": "general"}],
        },
        "core_gaps": ["machine learning"],
    }

    result = agent.analyze_transition(skill_gap_context, current_skills=["python", "docker"], user_profile=skill_gap_context["user_profile"])

    validated = CareerAgentOutputSchema.model_validate(result).model_dump()

    assert "feasibility_analysis" in result
    assert "transition_timeline" in result
    assert validated["input_profile"]["target_role"] == "AI Engineer"
    assert validated["skill_gap_context"]["core_gaps"] == ["machine learning"]
    assert validated["feasibility_analysis"]["target_role"] == "AI Engineer"
    assert "recommendation" in validated


def test_learning_agent_generates_roadmap():
    agent = LearningAgent(esco_repo=_FakeESCORepo(), llm_client=_FakeLLM())
    result = agent.generate_learning_roadmap(
        ["machine learning", "kubernetes"],
        ["python", "docker"],
        "AI Engineer",
    )

    assert "learning_path" in result
    assert "project_roadmap" in result
    assert result["learning_path"]["total_gaps"] == 2


def test_learning_agent_output_schema_validation():
    agent = LearningAgent(esco_repo=_FakeESCORepo(), llm_client=_FakeLLM())
    result = agent.generate_learning_roadmap(
        ["machine learning", "kubernetes"],
        ["python", "docker"],
        "AI Engineer",
    )
    validated = RoadmapOutputSchema.model_validate(result).model_dump()
    assert "phases" in validated
    assert "edges" in validated
    assert "metadata" in validated
    assert "learning_path" in validated
    assert validated["learning_path"]["total_gaps"] == 2


def test_learning_agent_accepts_skill_gap_dict():
    skill_gap = {
        "user_profile": {
            "employee_id": "EMP001",
            "name": "John Smith",
            "current_role": "Junior Developer",
            "target_role": "Java Backend Developer",
            "experience_years": 2,
        },
        "readiness_summary": {
            "readiness_score": 22.73,
            "readiness_category": "early_stage",
            "readiness_message": "Good starting point",
            "total_skills_required": 3,
            "skills_completed": 0,
            "skills_partial": 1,
            "skills_missing": 2,
        },
        "skill_analysis": {
            "matched_skills": [],
            "skill_gaps": [
                {"skill": "java", "user_level": 3, "required_level": 4, "gap": 1, "priority": "high",
                 "importance": "core", "category": "languages", "status": "in_progress"},
            ],
            "missing_core_skills": [
                {"skill": "spring", "user_level": 0, "required_level": 4, "gap": 4, "priority": "critical",
                 "importance": "core", "category": "frameworks", "status": "locked"},
                {"skill": "git", "user_level": 0, "required_level": 3, "gap": 3, "priority": "critical",
                 "importance": "core", "category": "tools", "status": "locked"},
            ],
            "missing_optional_skills": [],
            "priority_skills": [],
        },
        "core_gaps": ["spring", "git"],
    }

    agent = LearningAgent(esco_repo=_FakeESCORepo(), llm_client=_FakeLLM())
    result = agent.generate_learning_roadmap(skill_gap)

    assert result["metadata"]["target_role"] == "Java Backend Developer"
    assert result["metadata"]["employee_id"] == "EMP001"
    assert set(result["skill_gaps"]) == {"java", "spring", "git"}
    assert "phases" in result
    assert "edges" in result


def test_learning_agent_roadmap_has_phase_node_edge_structure():
    """Verify the roadmap.sh-style structure: each phase has nodes, nodes have depends_on."""
    skill_gap = {
        "user_profile": {"target_role": "Java Backend Developer"},
        "skill_analysis": {
            "skill_gaps": [],
            "missing_core_skills": [
                {"skill": "java", "user_level": 0, "required_level": 4, "gap": 4,
                 "priority": "critical", "importance": "core", "category": "languages", "status": "locked"},
            ],
            "missing_optional_skills": [],
        },
        "core_gaps": ["java"],
    }

    agent = LearningAgent(esco_repo=_FakeESCORepo(), llm_client=_FakeLLM())
    result = agent.generate_learning_roadmap(skill_gap)

    for phase in result["phases"]:
        assert "phase_id" in phase
        assert "phase_title" in phase
        assert "nodes" in phase
        for node in phase["nodes"]:
            assert "node_id" in node
            assert "label" in node
            assert "depends_on" in node


def test_market_agent_returns_gap_structure():
    agent = MarketAgent(esco_repo=_FakeESCORepo(), llm_client=_FakeLLM(), tech_keywords=["python", "docker"])
    result = agent.analyze_market_gaps({"skills": ["python"]})

    assert "market_gaps" in result
    assert "emerging_skills" in result
    assert "lifecycle" in result


def test_market_agent_output_schema_validation():
    agent = MarketAgent(esco_repo=_FakeESCORepo(), llm_client=_FakeLLM(), tech_keywords=["python", "docker"])
    result = agent.analyze_market_gaps({"skills": ["python"]})

    validated = MarketAgentOutputSchema.model_validate(result).model_dump()
    required_keys = {
        "market_gaps",
        "emerging_skills",
        "trending_skills",
        "vanishing_skills",
        "sources_used",
        "skill_details",
        "lifecycle",
        "source_health",
        "thought_process",
    }
    assert required_keys.issubset(set(validated.keys()))


def test_market_agent_collects_from_all_sources():
    class _FakeESCO:
        def search_skill(self, keyword: str):
            return [{"preferredLabel": {"en": f"{keyword}-esco"}}]

    class _FakeONET:
        def get_trending_skills(self):
            return ["onet-skill"]

    class _FakeGitHub:
        def get_trending_skills(self):
            return ["github-skill"]

    class _FakeYouTube:
        def get_technology_trends(self):
            return ["youtube-skill"]

    class _FakeGoogle:
        def get_trending_skills(self):
            return ["google-skill"]

        def get_skill_lifecycle(self, _skills):
            return {}

    class _FakeJobMarket:
        def get_role_market_skills(self, role: str, keywords=None):
            return ["job-market-skill"]

    agent = MarketAgent(
        esco_repo=_FakeESCO(),
        onet_repo=_FakeONET(),
        github_trends=_FakeGitHub(),
        youtube_signals=_FakeYouTube(),
        google_trends=_FakeGoogle(),
        job_market_signals=_FakeJobMarket(),
        llm_client=_FakeLLM(),
        tech_keywords=["python", "docker"],
    )
    result = agent.analyze_market_gaps({"skills": []})

    assert {"esco", "onet", "github", "youtube", "google", "job_market"}.issubset(set(result["sources_used"]))
    for source_name in ["esco", "onet", "github", "youtube", "google", "job_market"]:
        assert source_name in result["source_health"]
        assert result["source_health"][source_name]["status"] in {"ok", "empty", "unavailable"}


def test_market_agent_returns_role_specific_trends_for_role_rich_profile():
    class _FakeESCO:
        def search_skill(self, keyword: str):
            return [{"preferredLabel": {"en": f"{keyword}-esco"}}]

    class _FakeONET:
        def get_trending_skills(self):
            return ["llmops", "rag", "ai safety", "kubernetes"]

    class _FakeGitHub:
        def get_trending_skills(self):
            return ["langgraph", "llmops", "vector database", "python"]

    class _FakeYouTube:
        def get_technology_trends(self):
            return ["ai agents", "prompt engineering", "rag"]

    class _FakeGoogle:
        def get_trending_skills(self):
            return ["genai", "agentic ai", "llm"]

        def get_skill_lifecycle(self, skills):
            return {
                str(skill).lower(): {
                    "status": "trending",
                    "average_score": 50,
                    "recent_score": 70,
                    "trend_delta_percent": 40,
                }
                for skill in skills
            }

    agent = MarketAgent(
        esco_repo=_FakeESCO(),
        onet_repo=_FakeONET(),
        github_trends=_FakeGitHub(),
        youtube_signals=_FakeYouTube(),
        google_trends=_FakeGoogle(),
        llm_client=_FakeLLM(),
        tech_keywords=["senior ai engineer", "llm", "rag"],
    )

    result = agent.analyze_market_gaps(
        {
            "role": "Senior AI Engineer",
            "skills": ["python", "docker", "tensorflow"],
        }
    )

    assert isinstance(result.get("role_specific_trends"), list)
    assert len(result["role_specific_trends"]) > 0
    assert isinstance(result.get("industry_trending_skills"), list)
    assert set(result["role_specific_trends"]) != set(result.get("industry_trending_skills", []))
    assert not set(result["role_specific_trends"]).issubset(set(result.get("industry_trending_skills", [])))
    assert any(
        token in " ".join(result["role_specific_trends"]).lower()
        for token in ["rag", "llmops", "ai agents", "prompt engineering", "langgraph"]
    )


def test_talent_agent_ranks_candidates():
    employee_repo = [
        {"name": "Alex", "skills": ["python", "docker", "aws"]},
        {"name": "Sam", "skills": ["java", "spring"]},
    ]
    agent = TalentAgent(employee_repo=employee_repo, llm_client=None, skill_catalog=["python", "docker", "aws", "java"])
    matches = agent.match_employees("Need python docker aws experience")

    assert len(matches) >= 1
    assert matches[0]["employee"] == "Alex"


def test_typo_aip_gateway_maps_to_api_gateway():
    from pathlib import Path
    from src.services.workbook_skill_repository import WorkbookSkillRepository

    wb = WorkbookSkillRepository(
        str(Path(__file__).resolve().parent.parent / "Nextwork-Skill-Matrix3.0-Team 1.xlsx")
    )
    agent = SkillAgent(workbook_repo=wb)
    result = agent.analyze_skills(["aip gateway"], "Software Developer")
    missing = [item["skill"] for item in result["skill_analysis"]["missing_core_skills"]]
    assert "api gateway" not in missing
    assert "api gateway" in result["skill_analysis"]["matched_skills"]

    result2 = agent.analyze_skills(["aip gateway"], "Software Developer")
    assert result == result2


def test_generalized_phrase_variants_are_matched_deterministically():
    agent = SkillAgent(llm_client=_FakeLLM())

    assert agent._estimate_user_level("api gateway", ["api-gateway"]) >= 3
    assert agent._estimate_user_level("api gateway", ["apigateway"]) >= 3
    assert agent._estimate_user_level("microservices", ["micro service"]) >= 3
    assert agent._estimate_user_level("ci/cd", ["ci cd"]) >= 3
    assert agent._estimate_user_level("kubernetes", ["k8s"]) >= 3


def test_generalized_matching_avoids_unrelated_false_positive():
    agent = SkillAgent(llm_client=_FakeLLM())

    assert agent._estimate_user_level("api gateway", ["git workflow"]) == 0
    assert agent._estimate_user_level("microservices", ["monitoring dashboards"]) == 0


def test_resume_end_to_end_skill_gap_pipeline():
    from pathlib import Path
    from src.services.workbook_skill_repository import WorkbookSkillRepository

    wb = WorkbookSkillRepository(
        str(Path(__file__).resolve().parent.parent / "Nextwork-Skill-Matrix3.0-Team 1.xlsx")
    )
    tools = ResumeTools(workbook_repo=wb)
    extractor = tools.profile_extractor

    resume_path = Path(__file__).resolve().parent.parent / "sample_resume.txt"
    text = resume_path.read_text(encoding="utf-8")
    profile = extractor.extract(text, "Software Developer")

    agent = SkillAgent(workbook_repo=wb)
    result = agent.analyze_skills(profile["skills"], "Software Developer")
    matched = result["skill_analysis"]["matched_skills"]
    missing = result["skill_analysis"]["missing_core_skills"]
    gaps = result["skill_analysis"]["skill_gaps"]

    assert len(matched) > 0
    assert len(missing) + len(gaps) > 0
    assert result["skill_source"]["provider"] == "workbook"


def test_stability_loop_skill_gap_identical_outputs():
    from pathlib import Path
    from src.services.workbook_skill_repository import WorkbookSkillRepository

    wb = WorkbookSkillRepository(
        str(Path(__file__).resolve().parent.parent / "Nextwork-Skill-Matrix3.0-Team 1.xlsx")
    )
    tools = ResumeTools(workbook_repo=wb)
    extractor = tools.profile_extractor

    resume_path = Path(__file__).resolve().parent.parent / "sample_resume.txt"
    text = resume_path.read_text(encoding="utf-8")
    profile = extractor.extract(text, "Software Developer")

    results = []
    for _ in range(5):
        agent = SkillAgent(workbook_repo=wb)
        result = agent.analyze_skills(profile["skills"], "Software Developer")
        results.append(result)

    assert all(result == results[0] for result in results)