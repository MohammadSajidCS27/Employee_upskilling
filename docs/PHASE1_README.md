# Phase 1: Employee Intelligence Layer

## Implemented Agents

1. Resume Agent - Extracts role, experience, skills, and education from resumes
2. Skill Agent - Calculates readiness score and identifies core gaps
3. Market Agent - Identifies market gaps and emerging skills
4. Career Agent - Evaluates transition readiness for target roles
5. Learning Agent - Generates learning roadmaps
6. Talent Agent - Matches employees to job descriptions

## Quick Start

```bash
pip install -r requirements.txt
python demo_phase1.py
python run.py  # Start FastAPI server
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| /analyze/resume | POST | Analyze resume text |
| /analyze/resume/file | POST | Analyze uploaded resume file |
| /analyze/skill-gaps | POST | Get role readiness and skill gaps |
| /analyze/market-gaps | POST | Get market and emerging skill gaps |
| /analyze/transition | POST | Evaluate career transition |
| /generate/roadmap | POST | Generate learning roadmap |
| /talent/match | POST | Match employees to job descriptions |
| /workflow/employee | POST | Run full employee workflow |
| /workflow/manager | POST | Run manager workflow |
| /pipeline/complete | POST | Run complete LangGraph pipeline |

## Tests

- tests/test_agents.py - LangGraph-focused agent tests
- tests/test_workflow_phase1.py - Workflow endpoint integration tests
- tests/test_api_production.py - API production checks
