from fastapi.testclient import TestClient

from src.config import settings
from src.main import app


def test_health_endpoint_includes_runtime_status():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"healthy", "degraded"}
    assert payload["database"] in {"up", "down"}
    assert payload["environment"] == settings.app_env


def test_security_headers_are_set():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_resume_upload_rejects_unsupported_file_type():
    with TestClient(app) as client:
        response = client.post(
            "/analyze/resume/file",
            files={"file": ("resume.exe", b"fake", "application/octet-stream")},
        )

    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_resume_upload_accepts_pdf():
    """PDF files should be accepted and text extracted."""
    with TestClient(app) as client:
        # Create a valid PDF with extractable text
        pdf_content = (
            b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> >>\nendobj\n"
            b"4 0 obj\n<< /Length 200 >>\nstream\nBT\n/F1 24 Tf\n100 700 Td\n(Software Engineer) Tj\nET\nendstream\nendobj\n"
            b"xref\n0 5\n0000000000 65535 f\n0000000015 00000 n\n0000000068 00000 n\n0000000124 00000 n\n0000000261 00000 n\n"
            b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n470\n%%EOF"
        )
        response = client.post(
            "/analyze/resume/file",
            files={"file": ("resume.pdf", pdf_content, "application/pdf")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert "profile" in payload
    assert "extracted_text" in payload


def test_roles_categories_endpoint():
    """Get available role categories for selection UI."""
    with TestClient(app) as client:
        response = client.get("/roles/categories")

    assert response.status_code == 200
    payload = response.json()
    assert "categories" in payload
    assert len(payload["categories"]) >= 7
    categories = [c["category"] for c in payload["categories"]]
    assert "Engineering" in categories


def test_resume_analysis_returns_role_suggestions():
    """Resume analysis should return role suggestions for user confirmation."""
    with TestClient(app) as client:
        response = client.post(
            "/analyze/resume",
            json={"text": "Senior Python Developer with 5 years experience in Django and Flask"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert "role_suggestions" in payload
    assert payload["needs_role_confirmation"] is True


def test_resume_upload_returns_role_suggestions():
    """PDF resume upload should return role suggestions for user confirmation."""
    with TestClient(app) as client:
        pdf_content = (
            b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> >>\nendobj\n"
            b"4 0 obj\n<< /Length 200 >>\nstream\nBT\n/F1 24 Tf\n100 700 Td\n(Python Developer) Tj\nET\nendstream\nendobj\n"
            b"xref\n0 5\n0000000000 65535 f\n0000000015 00000 n\n0000000068 00000 n\n0000000124 00000 n\n0000000261 00000 n\n"
            b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n470\n%%EOF"
        )
        response = client.post(
            "/analyze/resume/file",
            files={"file": ("resume.pdf", pdf_content, "application/pdf")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert "role_suggestions" in payload


def test_resume_upload_rejects_too_large_file(monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    oversized = b"a" * (1 * 1024 * 1024 + 1)

    with TestClient(app) as client:
        response = client.post(
            "/analyze/resume/file",
            files={"file": ("resume.txt", oversized, "text/plain")},
        )

    assert response.status_code == 413
