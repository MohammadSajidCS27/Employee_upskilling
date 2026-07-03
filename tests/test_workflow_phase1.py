from fastapi.testclient import TestClient

from src.main import app


def test_employee_workflow_endpoint_returns_compatible_shape(monkeypatch):
    def fake_market_analysis(profile):
        return {
            "market_gaps": ["kubernetes"],
            "emerging_skills": ["kubernetes", "mlops"],
        }

    monkeypatch.setattr("src.main._run_market_analysis", fake_market_analysis)

    payload = {
        "resume_text": (
            "Senior Software Engineer\n"
            "Experience: 5 years\n"
            "Skills: Python, Docker, AWS\n"
            "Education: Bachelor of Science in Computer Science"
        ),
        "target_role": "AI Engineer",
    }

    with TestClient(app) as client:
        response = client.post("/workflow/employee", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert "profile" in data
    assert "readiness_score" in data
    assert "core_gaps" in data
    assert "market_gaps" in data
    assert "roadmap" in data


def test_manager_workflow_endpoint_returns_matches_shape(monkeypatch):
    class _FakePostgres:
        def get_employee_profiles(self):
            return [{"name": "Alex", "skills": ["python", "docker", "aws"]}]

    app.state.postgres_service = _FakePostgres()

    payload = {"job_description": "Need python, docker, aws"}

    with TestClient(app) as client:
        response = client.post("/workflow/manager", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert "learning_resources" in data
    assert "matches" in data["learning_resources"]
