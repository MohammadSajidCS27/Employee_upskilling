from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import os
import uuid
import json
import logging
from datetime import datetime, timezone
import asyncio
import re
from pydoc import text
from src.agents.langgraph_orchestrator import UnifiedAgentOrchestrator
from src.agents.langgraph_market_agent import MarketAgent
from src.agents.langgraph_talent_agent import TalentAgent
from src.config import settings
from src.services.postgres_service import PostgreSQLService
from src.services.esco_repository import ESCORepository
from src.services.onet_repository import ONETRepository
from src.services.workbook_skill_repository import WorkbookSkillRepository
from src.services.google_trends_api import GoogleTrendsAPI
from src.services.github_trends_api import GitHubTrendsAPI
from src.services.youtube_signals_api import YouTubeSignalsAPI
from src.services.job_market_signals_api import JobMarketSignalsAPI
from src.services.llm_client import GroqClient
from src.utils.password import verify_password, hash_password
from youtube_client import (
    YouTubeAuthError,
    YouTubeClientError,
    fetch_videos,
    fetch_videos_from_search_page,
    format_videos,
    node_id_to_query,
    validate_youtube_api_key,
)

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST_DIR = PROJECT_ROOT / "frontend" / "dist"
FRONTEND_ASSETS_DIR = FRONTEND_DIST_DIR / "assets"
FRONTEND_PUBLIC_DIR = PROJECT_ROOT / "frontend" / "public"


def _build_llm_client() -> Optional[GroqClient]:
    return GroqClient(settings.groq_api_key) if settings.groq_api_key else None


def _configuration_warnings() -> List[str]:
    warnings: List[str] = []
    if settings.app_env.lower() == "prod" and not settings.groq_api_key:
        warnings.append("GROQ_API_KEY is not configured for prod environment")
    if settings.app_env.lower() == "prod" and settings.session_secret == "siemens-workforce-intelligence-dev-secret":
        warnings.append("SESSION_SECRET is using the insecure default; set a strong value for prod")
    if not settings.youtube_api_key:
        warnings.append("YOUTUBE_API_KEY is not configured; YouTube market signals are disabled")
    if not settings.github_token:
        warnings.append("GITHUB_TOKEN is not configured; GitHub API may be rate-limited")
    if not settings.onet_api_key:
        warnings.append("ONET_API_KEY is not configured; O*NET lookups may use fallback data")
    return warnings


def _build_esco_repository() -> ESCORepository:
    return ESCORepository(
        cache_dir=settings.esco_cache_path,
        role_skill_map=settings.esco_role_skill_map,
        default_skills=settings.skill_catalog,
    )


def _build_onet_repository(esco_repo: ESCORepository) -> ONETRepository:
    return ONETRepository(
        api_key=settings.onet_api_key or None,
        esco_repo=esco_repo,
        trending_skills=settings.onet_trending_skills,
        occupation_skill_map=settings.onet_occupation_skill_map,
    )


def _build_workbook_repository() -> Optional[WorkbookSkillRepository]:
    workbook_path = str(settings.skill_matrix_workbook_path or "").strip()
    if not workbook_path:
        return None
    repo = WorkbookSkillRepository(workbook_path=workbook_path)
    if not Path(workbook_path).exists():
        logger.warning("Workbook skill matrix file not found at '%s'; falling back to ESCO/O*NET", workbook_path)
    return repo


def _parse_allowed_origins() -> List[str]:
    return [origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()]


def _read_frontend_index() -> str:
        frontend_index = FRONTEND_DIST_DIR / "index.html"
        if frontend_index.exists():
                return frontend_index.read_text(encoding="utf-8")

        return """
        <!doctype html>
        <html>
            <head><title>UI Not Built</title></head>
            <body>
                <h2>Frontend build not found</h2>
                <p>Run <code>cd frontend && npm install && npm run build</code> to serve the React UI.</p>
            </body>
        </html>
        """


@asynccontextmanager
async def lifespan(app: FastAPI):
    postgres_service: Optional[PostgreSQLService] = None
    try:
        postgres_service = PostgreSQLService(settings.database_url)
        postgres_service.init_db()
    except Exception as error:
        logger.exception("PostgreSQL startup failed; continuing without DB-backed endpoints: %s", error)
        postgres_service = None
    llm_client = _build_llm_client()
    esco_repo = _build_esco_repository()
    onet_repo = _build_onet_repository(esco_repo)
    workbook_repo = _build_workbook_repository()
    
    # Initialize the unified LangGraph agent orchestrator
    app.state.agent_orchestrator = UnifiedAgentOrchestrator(
        llm_client=llm_client.client if llm_client else None,
        esco_repo=esco_repo,
        onet_repo=onet_repo,
        workbook_repo=workbook_repo,
    )
    
    app.state.llm_client = llm_client
    app.state.postgres_service = postgres_service
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
if FRONTEND_DIST_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(FRONTEND_DIST_DIR), html=True), name="ui")
if FRONTEND_ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_ASSETS_DIR), html=False), name="assets")
if FRONTEND_PUBLIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_PUBLIC_DIR), html=False), name="public")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, max_age=86400, same_site="lax", https_only=False)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    is_frontend_route = request.url.path.startswith("/ui") or request.url.path.startswith("/assets")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN" if is_frontend_route else "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


def _get_agent_orchestrator(request: Request) -> UnifiedAgentOrchestrator:
    orchestrator = getattr(request.app.state, "agent_orchestrator", None)
    if orchestrator is None:
        logger.warning("agent_orchestrator missing in app state; initializing lazily")
        llm_client = _build_llm_client()
        esco_repo = _build_esco_repository()
        orchestrator = UnifiedAgentOrchestrator(
            llm_client=llm_client.client if llm_client else None,
            esco_repo=esco_repo,
            onet_repo=_build_onet_repository(esco_repo),
            workbook_repo=_build_workbook_repository(),
        )
        request.app.state.agent_orchestrator = orchestrator
        if not hasattr(request.app.state, "llm_client"):
            request.app.state.llm_client = llm_client
    return orchestrator


def _get_postgres_service(request: Request) -> Optional[PostgreSQLService]:
    postgres_service = getattr(request.app.state, "postgres_service", None)
    if postgres_service is None:
        logger.warning("postgres_service missing in app state; initializing lazily")
        try:
            postgres_service = PostgreSQLService(settings.database_url)
            postgres_service.init_db()
            request.app.state.postgres_service = postgres_service
        except Exception as error:
            logger.exception("PostgreSQL lazy initialization failed: %s", error)
            request.app.state.postgres_service = None
            postgres_service = None
    return postgres_service


def _get_llm_client(request: Request) -> Optional[GroqClient]:
    llm_client = getattr(request.app.state, "llm_client", None)
    if llm_client is None and settings.groq_api_key:
        llm_client = _build_llm_client()
        request.app.state.llm_client = llm_client
    return llm_client


def _extract_profile_from_text(orchestrator: UnifiedAgentOrchestrator, text: str) -> Dict[str, Any]:
    profile_extractor = orchestrator.resume_agent.tools.profile_extractor
    return {
        "role": profile_extractor.extract_role(text),
        "experience": profile_extractor.extract_experience(text),
        "skills": profile_extractor.extract_skills(text),
        "education": profile_extractor.extract_education(profile_extractor._split_lines(text)),
    }


def _roadmap_compat_payload(learning_roadmap: Dict[str, Any]) -> Dict[str, Any]:
    learning_path = learning_roadmap.get("learning_path", {})
    phases = learning_path.get("phases", {})
    project_roadmap = learning_roadmap.get("project_roadmap", {})

    foundation = phases.get("foundation", {})
    intermediate = phases.get("intermediate", {})
    advanced = phases.get("advanced", {})

    return {
        "foundation": {
            "skills": foundation.get("skills", []),
            "duration_weeks": foundation.get("duration_weeks", 0),
        },
        "core": {
            "skills": intermediate.get("skills", []),
            "duration_weeks": intermediate.get("duration_weeks", 0),
        },
        "projects": {
            "projects": [project.get("project", "") for project in project_roadmap.get("projects", [])],
            "details": project_roadmap.get("projects", []),
        },
        "advanced": {
            "skills": advanced.get("skills", []),
            "duration_weeks": advanced.get("duration_weeks", 0),
        },
        "metadata": {
            "generated_method": "langgraph_learning_agent",
            "total_estimated_weeks": learning_path.get("total_estimated_weeks", 0),
        },
    }


def _run_market_analysis(profile: Dict[str, Any]) -> Dict[str, Any]:
    esco_repo = _build_esco_repository()
    onet_repo = _build_onet_repository(esco_repo)
    llm_client = _build_llm_client()
    
    # Combine market keywords with role keywords for better matching
    role = str(profile.get("role") or "").lower()
    combined_keywords = settings.market_keywords.copy()
    if role:
        combined_keywords.insert(0, role)
    
    agent = MarketAgent(
        esco_repo=esco_repo,
        onet_repo=onet_repo,
        google_trends=GoogleTrendsAPI(keywords=settings.market_keywords),
        github_trends=GitHubTrendsAPI(
            token=settings.github_token or None,
            trending_window_days=settings.github_trending_window_days,
        ),
        youtube_signals=YouTubeSignalsAPI(
            api_key=settings.youtube_api_key or None,
            search_keywords=settings.youtube_keywords,
        ),
        job_market_signals=JobMarketSignalsAPI(),
        llm_client=llm_client.client if llm_client else None,
        tech_keywords=combined_keywords,
        max_market_gaps=settings.max_market_gaps,
        max_emerging_skills=settings.max_emerging_skills,
    )
    return agent.analyze_market_gaps(profile)


def _validate_resume_upload(filename: str, content_type: str) -> None:
    allowed_extensions = {".txt", ".md", ".pdf"}
    allowed_mime_types = {
        "text/plain",
        "text/markdown",
        "application/octet-stream",
        "application/pdf",
    }
    extension = os.path.splitext(filename.lower())[1]
    if extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Unsupported file type. Use txt, md, or pdf.")
    if content_type and content_type not in allowed_mime_types:
        raise HTTPException(status_code=400, detail="Unsupported content type for uploaded resume.")


def _decode_resume_upload_content(content: bytes, filename: str = "upload.pdf") -> str:
    """Decode uploaded txt/md/pdf content with safe fallbacks.

    We accept common encodings to avoid unnecessary 500s for valid text files
    saved outside UTF-8. PDFs are extracted using pdfplumber.
    """
    extension = os.path.splitext(filename.lower())[1]
    if extension == ".pdf":
        return _extract_pdf_text(content, filename)
    
    for encoding in ("utf-8", "utf-8-sig", "utf-16", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(
        status_code=400,
        detail="Unable to decode uploaded resume text. Please upload a plain TXT/MD file encoded as UTF-8.",
    )


def _extract_pdf_text(pdf_bytes: bytes, filename: str = "upload.pdf") -> str:
    """Extract text from PDF bytes using the orchestrator's tools."""
    import tempfile
    from pathlib import Path
    import pdfplumber
    
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", prefix=f"resume_{filename}_", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name
        
        try:
            with pdfplumber.open(tmp_path) as pdf:
                text = ""
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            
            if not text.strip():
                raise HTTPException(
                    status_code=400,
                    detail="No text could be extracted from PDF. The file may be image-based or corrupted.",
                )
            return text
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to extract text from PDF: {str(e)}",
        )


def _suggest_roles_from_profile(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggest role categories and specific roles based on extracted profile."""
    skills = set(skill.lower() for skill in profile.get("skills", []))
    extracted_role = (profile.get("role") or "").lower()
    
    # Return all categories with roles, highlighting those matching extracted role/skills
    return [
        {
            "category": cat["category"],
            "icon": cat["icon"],
            "matched_roles": cat["roles"],
            "is_relevant": any(
                role.lower() in extracted_role or extracted_role in role.lower() or
                any(skill in role.lower() for skill in skills)
                for role in cat["roles"]
            )
        }
        for cat in ROLE_CATEGORIES
    ]


def _persist_generated_roadmap_snapshot(roadmap: Dict[str, Any]) -> None:
    """Write generated roadmap to cache for quick inspection/debugging."""
    snapshot_dir = PROJECT_ROOT / "cache" / "generated_roadmaps"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    slug = _roadmap_slug_from(roadmap)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_path = snapshot_dir / f"{slug}-{timestamp}.json"
    latest_path = snapshot_dir / "latest-roadmap.json"

    payload = json.dumps(roadmap, indent=2, ensure_ascii=False)
    snapshot_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")

    logger.info(
        "[ROADMAP GENERATION] Snapshot written: %s (latest: %s)",
        snapshot_path,
        latest_path,
    )
def _allocate_node_videos(postgres_service: PostgreSQLService, roadmap: Dict[str, Any], max_per_node: int = 5) -> None:
    """Fetch and persist YouTube videos for all nodes in a generated roadmap."""
    if postgres_service is None:
        logger.warning("[RESOURCE ALLOCATION] No DB service; skipping video allocation")
        return

    roadmap_slug = _roadmap_slug_from(roadmap)
    total_videos = 0
    youtube_enabled, youtube_reason = validate_youtube_api_key()
    if not youtube_enabled:
        logger.warning(
            "[RESOURCE ALLOCATION] Live YouTube enrichment disabled (%s); using cached DB videos only",
            youtube_reason,
        )
    auth_error_logged = False

    for phase in roadmap.get("phases", []):
        for node in phase.get("nodes", []):
            node_id = str(node.get("node_id", "")).strip()
            if not node_id:
                continue

            try:
                # ✅ CACHE CHECK — reuse existing videos, zero DB writes, zero API calls
                cached_videos = postgres_service.get_videos_by_node_id(node_id)
                if cached_videos:
                    total_videos += len(cached_videos)
                    logger.info(
                        "[RESOURCE ALLOCATION] Reused %d cached videos for node=%s (no API call, no DB write)",
                        len(cached_videos),
                        node_id,
                    )
                    continue  # ← Skip everything below ✅

                # ⬇️ No cache — fetch fresh from YouTube (first time only)
                if not youtube_enabled:
                    continue
                queries = _build_node_video_queries(node, node_id)
                for query in queries:
                    try:
                        api_results = fetch_videos(query, max_results=max_per_node)
                        videos = _filter_relevant_videos(format_videos(api_results), queries)
                        if not videos:
                            continue
                        stored = postgres_service.upsert_node_videos(roadmap_slug, node_id, videos)
                        total_videos += stored
                        logger.debug(
                            "[RESOURCE ALLOCATION] Fetched %d videos for node=%s with query='%s'",
                            stored,
                            node_id,
                            query,
                        )
                        break
                    except YouTubeAuthError:
                        youtube_enabled = False
                        if not auth_error_logged:
                            logger.warning(
                                "[RESOURCE ALLOCATION] YouTube API authorization failed; disabling live enrichment for this run"
                            )
                            auth_error_logged = True
                        break
                    except YouTubeClientError as exc:
                        logger.warning(
                            "[RESOURCE ALLOCATION] Live YouTube fetch failed for node=%s query='%s' (%s)",
                            node_id,
                            query,
                            exc,
                        )
            except Exception as exc:
                logger.warning("[RESOURCE ALLOCATION] Skipped node=%s due to error: %s", node_id, exc)
                continue

    logger.info(
        "[RESOURCE ALLOCATION] Allocated %d videos for roadmap=%s",
        total_videos, roadmap_slug
    )


# â”€â”€ In-memory roadmap store (keyed by roadmap_slug â†’ roadmap dict) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# This is populated by POST /generate/roadmap and read by the /roadmap/* endpoints.
# Replace with a DB-backed store when persistence is required.
_roadmap_store: Dict[str, Dict[str, Any]] = {}

# â”€â”€ In-memory progress store (keyed by "{roadmap_slug}:{user_id}:{node_id}") â”€â”€
_node_status_store: Dict[str, str] = {}

def _roadmap_slug_from(roadmap: Dict[str, Any], user_email: str = None) -> str:
    """Derive a stable slug from the roadmap payload, unique per user."""
    base_slug = str(
        roadmap.get("metadata", {}).get("roadmap_slug")
        or roadmap.get("roadmap_id")
        or "generated"
    ).strip() or "generated"

    if user_email:
        # e.g. "roadmap-agent--emp--john-at-siemens-com"
        safe_email = (
            user_email.lower()
            .replace("@", "-at-")
            .replace(".", "-")
            .replace("+", "-")
        )
        return f"{base_slug}--{safe_email}"

    return base_slug


def _tokenize_text(value: str) -> set[str]:
    text_value = str(value or "").lower()
    parts = re.findall(r"[a-z0-9]+", text_value)
    stop_words = {"and", "or", "for", "the", "with", "from", "into", "tutorial", "basics"}
    return {part for part in parts if len(part) > 2 and part not in stop_words}


def _build_node_video_queries(node: Dict[str, Any], node_id: str) -> list[str]:
    queries: list[str] = []
    roadmap_hint = str(node.get("source_roadmap") or "").strip()
    title_hint = str(node.get("label") or node.get("title") or "").strip()
    skill_hint = str(node.get("matched_skill") or "").strip()
    id_hint = node_id_to_query(node_id)

    candidates = [
        f"{roadmap_hint} {title_hint}".strip(),
        f"{roadmap_hint} {skill_hint}".strip(),
        title_hint,
        skill_hint,
        id_hint,
    ]
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if normalized and normalized not in queries:
            queries.append(normalized)
    return queries


def _filter_relevant_videos(videos: list[dict[str, Any]], queries: list[str]) -> list[dict[str, Any]]:
    query_tokens: set[str] = set()
    for query in queries:
        query_tokens.update(_tokenize_text(query))

    if not query_tokens:
        return videos

    filtered: list[dict[str, Any]] = []
    for video in videos:
        haystack = f"{video.get('title', '')} {video.get('channel', '')}"
        video_tokens = _tokenize_text(haystack)
        if query_tokens.intersection(video_tokens):
            filtered.append(video)

    return filtered

def _build_skill_rows(
    roadmap: Dict[str, Any], user_id: str, roadmap_slug: str
) -> List[Dict[str, Any]]:
    """
    Flatten phases â†’ nodes into per-skill rows that the frontend expects:
    { skill, total, completed, nodes: [{node_id, title, status}] }
    """
    skill_map: Dict[str, Dict[str, Any]] = {}

    for phase in roadmap.get("phases", []):
        skill = str(phase.get("skill") or phase.get("phase_title") or "General")
        if skill not in skill_map:
            skill_map[skill] = {"skill": skill, "nodes": []}

        for node in phase.get("nodes", []):
            node_id = str(node.get("node_id", ""))
            store_key = f"{roadmap_slug}:{user_id}:{node_id}"
            persisted_status = _node_status_store.get(store_key)
            status = persisted_status or node.get("status") or "not_started"
            skill_map[skill]["nodes"].append(
                {
                    "node_id": node_id,
                    "title": node.get("label") or node.get("title") or node_id,
                    "status": status,
                    "type": node.get("type", ""),
                    "importance": node.get("importance", ""),
                    "phase_title": phase.get("phase_title", ""),
                    "depends_on": node.get("depends_on", []),
                }
            )

    rows = []
    for skill, data in skill_map.items():
        nodes = data["nodes"]
        completed = sum(1 for n in nodes if n["status"] == "completed")
        rows.append(
            {
                "skill": skill,
                "total": len(nodes),
                "completed": completed,
                "nodes": nodes,
            }
        )
    return rows

def _compute_progress(
    roadmap: Dict[str, Any], user_id: str, roadmap_slug: str
) -> Dict[str, Any]:
    """Compute overall completion stats for a roadmap + user."""
    all_nodes: List[Dict[str, Any]] = [
        n for p in roadmap.get("phases", []) for n in p.get("nodes", [])
    ]
    total = len(all_nodes)
    completed = 0
    in_progress = 0
    not_started = 0

    for node in all_nodes:
        node_id = str(node.get("node_id", ""))
        store_key = f"{roadmap_slug}:{user_id}:{node_id}"
        status = _node_status_store.get(store_key) or node.get("status") or "not_started"
        if status == "completed":
            completed += 1
        elif status == "in_progress":
            in_progress += 1
        else:
            not_started += 1

    completion_rate = round((completed / total * 100), 1) if total else 0.0
    return {
        "roadmap_slug": roadmap_slug,
        "user_id": user_id,
        "total": total,
        "completed": completed,
        "in_progress": in_progress,
        "not_started": not_started,
        "completion_rate": completion_rate,
    }




class NodeStatusRequest(BaseModel):
    status: str = Field(...,pattern="^(not_started|in_progress|completed)$", description="Node status must be one of: not_started, in_progress, completed")

class ResumeTextRequest(BaseModel):
    text: str = Field(..., min_length=10)

class ResumeUploadResponse(BaseModel):
    extracted_text: str
    profile: Dict[str, Any]
    role_suggestions: Optional[List[Dict[str, Any]]] = None

ROLE_CATEGORIES = [
    {
        "category": "Engineering",
        "icon": "💻",
        "roles": [
            "Software Engineer",
            "Senior Software Engineer",
            "Junior Software Engineer",
            "Lead Software Engineer",
            "Staff Software Engineer",
            "Java Developer",
            "Python Developer",
            "JavaScript Developer",
            "TypeScript Developer",
            "Go Developer",
            "C++ Developer",
            ".NET Developer",
            "Node.js Developer",
            "React Developer",
            "Angular Developer",
            "Vue.js Developer",
            "Frontend Developer",
            "Backend Developer",
            "Full Stack Developer",
        ],
    },
    {
        "category": "Architecture",
        "icon": "🏛️",
        "roles": [
            "Software Architect",
            "Solution Architect",
            "Cloud Architect",
            "Enterprise Architect",
            "System Architect",
            "Technical Architect",
            "Principal Engineer",
            "Distinguished Engineer",
        ],
    },
    {
        "category": "Leadership",
        "icon": "👥",
        "roles": [
            "Engineering Manager",
            "Tech Lead",
            "Team Lead",
            "Scrum Master",
            "Product Manager",
            "Engineering Director",
            "VP of Engineering",
            "CTO",
        ],
    },
    {
        "category": "Design",
        "icon": "🎨",
        "roles": [
            "UI Designer",
            "UX Designer",
            "UI/UX Designer",
            "Product Designer",
            "Interaction Designer",
            "Visual Designer",
            "Design Lead",
        ],
    },
    {
        "category": "DevOps & Cloud",
        "icon": "☁️",
        "roles": [
            "DevOps Engineer",
            "Site Reliability Engineer",
            "Cloud Engineer",
            "Platform Engineer",
            "Infrastructure Engineer",
            "Release Engineer",
            "Build Engineer",
        ],
    },
    {
        "category": "Quality Assurance",
        "icon": "🧪",
        "roles": [
            "QA Engineer",
            "Automation Tester",
            "Manual Tester",
            "SDET",
            "QA Lead",
            "Test Engineer",
        ],
    },
    {
        "category": "Data & Analytics",
        "icon": "📊",
        "roles": [
            "Data Engineer",
            "Data Scientist",
            "Data Analyst",
            "ML Engineer",
            "Data Architect",
            "Analytics Engineer",
            "Business Intelligence Analyst",
        ],
    },
    {
        "category": "Security",
        "icon": "🔐",
        "roles": [
            "Security Engineer",
            "Security Analyst",
            "Penetration Tester",
            "Security Architect",
            "Application Security Engineer",
        ],
    },
    {
        "category": "Mobile",
        "icon": "📱",
        "roles": [
            "Mobile Developer",
            "iOS Developer",
            "Android Developer",
            "Flutter Developer",
            "React Native Developer",
        ],
    },
    {
        "category": "Operations",
        "icon": "⚙️",
        "roles": [
            "Technical Operations",
            "IT Operations",
            "Site Operations",
            "Platform Operations",
            "Cloud Operations",
        ],
    },
]

class JobDescriptionRequest(BaseModel):
    job_description: str = Field(..., min_length=10, max_length=10000)


class EmployeeWorkflowRequest(BaseModel):
    resume_text: str = Field(..., min_length=10)
    target_role: Optional[str] = Field(default="")


class ManagerWorkflowRequest(BaseModel):
    job_description: str = Field(..., min_length=10, max_length=10000)

class TransitionRequest(BaseModel):
    profile: dict = Field(..., description="Employee profile with skills")
    target_role: str = Field(..., min_length=1)
    skill_gap_context: Optional[Dict[str, Any]] = Field(default=None, description="Skill-gap context from Skill Agent")

class RoadmapRequest(BaseModel):
    profile: Optional[dict] = Field(default=None, description="Employee profile (optional; extracted from skill_gap if omitted)")
    skill_gap: Optional[Dict[str, Any]] = Field(default=None, description="Full skill-gap payload from Skill Agent")
    gaps: List[str] = Field(default_factory=list)
    target_role: Optional[str] = Field(default=None, min_length=1)


class MarketGapRequest(BaseModel):
    skills: List[str] = Field(default_factory=list)
    role: Optional[str] = Field(default="")


class RoleSelectionRequest(BaseModel):
    profile: dict = Field(..., description="Employee profile from resume analysis")
    selected_role: str = Field(..., min_length=1, description="User-selected role")


class RoleConfirmationResponse(BaseModel):
    status: str
    profile: dict
    selected_role: str
    skills_required: Optional[List[str]] = None
    skill_gaps: Optional[List[str]] = None


@app.get("/roles/categories")
async def get_role_categories():
    """Get all available role categories and their roles for user selection."""
    return {"categories": ROLE_CATEGORIES}


@app.post("/analyze/resume/confirm-role")
async def confirm_role_and_analyze(request: RoleSelectionRequest, http_request: Request):
    """Confirm user's role selection and proceed with skill gap analysis."""
    try:
        orchestrator = _get_agent_orchestrator(http_request)
        profile = request.profile
        selected_role = request.selected_role
        
        current_skills = [str(skill) for skill in profile.get("skills", []) if str(skill).strip()]
        
        skill_analysis = orchestrator.skill_agent.analyze_skills(
            current_skills,
            selected_role,
            user_profile=profile,
        )
        
        skills_required = skill_analysis.get("readiness_summary", {}).get("total_skills_required", 0)
        core_gaps = skill_analysis.get("core_gaps", [])[: settings.max_core_gaps]
        
        return {
            "status": "success",
            "profile": profile,
            "selected_role": selected_role,
            "skills_required": skills_required,
            "skill_gaps": core_gaps,
            "skill_analysis": skill_analysis,
        }
    except Exception:
        logger.exception("Role confirmation error")
        raise HTTPException(status_code=500, detail="Error analyzing role")

@app.get("/", response_class=HTMLResponse)
async def root():
    login_html_path = PROJECT_ROOT / "frontend" / "public" / "siemens-login.html"
    if login_html_path.exists():
        content = login_html_path.read_text(encoding="utf-8-sig")
        return HTMLResponse(content=content)
    raise HTTPException(status_code=404, detail="Login page not found")


@app.get("/meta/frameworks")
async def frameworks_metadata():
    return {
        "backend": ["FastAPI", "LangGraph", "LangChain", "SQLAlchemy", "Pydantic"],
        "frontend": ["React (Vite)"],
        "databases": ["PostgreSQL", "ChromaDB"],
    }

@app.post("/analyze/resume")
async def analyze_resume(request: ResumeTextRequest, http_request: Request):
    try:
        text = request.text[:5000]
        orchestrator = _get_agent_orchestrator(http_request)
        profile = _extract_profile_from_text(orchestrator, text)
        role_suggestions = _suggest_roles_from_profile(profile)
        return {
            "extracted_text": text,
            "profile": profile,
            "role_suggestions": role_suggestions,
            "needs_role_confirmation": True,
        }
    except Exception:
        logger.exception("Resume parsing error")
        raise HTTPException(status_code=500, detail="Error parsing resume")

@app.post("/analyze/resume/file")
async def analyze_resume_file(http_request: Request, file: UploadFile = File(...)):
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")
        _validate_resume_upload(file.filename, file.content_type or "")
        content = await file.read()
        max_upload_bytes = settings.max_upload_mb * 1024 * 1024
        if len(content) > max_upload_bytes:
            raise HTTPException(status_code=413, detail=f"File too large. Max allowed size is {settings.max_upload_mb} MB")

        orchestrator = _get_agent_orchestrator(http_request)
        text = _decode_resume_upload_content(content, file.filename) if isinstance(content, bytes) else str(content)

        if not text or not str(text).strip():
            raise HTTPException(status_code=400, detail="Uploaded resume has no readable text content.")

        extracted_text = text[:5000]
        profile = _extract_profile_from_text(orchestrator, extracted_text)
        
        role_suggestions = _suggest_roles_from_profile(profile)

        return {
            "extracted_text": extracted_text,
            "profile": profile,
            "role_suggestions": role_suggestions,
            "needs_role_confirmation": True,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Resume parsing error")
        raise HTTPException(status_code=500, detail="Error parsing resume")

@app.post("/analyze/skill-gaps")
async def analyze_skill_gaps(profile: dict, http_request: Request):
    try:
        orchestrator = _get_agent_orchestrator(http_request)
        target_role = str(profile.get("target_role") or profile.get("role") or settings.default_role_title)
        current_skills = [str(skill) for skill in profile.get("skills", []) if str(skill).strip()]
        analysis = orchestrator.skill_agent.analyze_skills(
            current_skills,
            target_role,
            user_profile=profile,
        )

        return {
            "readiness_score": analysis.get("readiness_summary", {}).get("readiness_score", 0),
            "core_gaps": analysis.get("core_gaps", [])[: settings.max_core_gaps],
            "expected_skills_count": analysis.get("readiness_summary", {}).get("total_skills_required", 0),
            "sources_used": [
                str(analysis.get("skill_source", {}).get("provider", "unknown")),
                str(analysis.get("skill_source", {}).get("source", "unknown")),
            ],
            "skill_gap_json": analysis,
            "details": analysis,
        }
    except Exception:
        logger.exception("Skill analysis error")
        raise HTTPException(status_code=500, detail="Error analyzing skills")


@app.post("/analyze/market-gaps")
async def analyze_market_gaps(request: MarketGapRequest):
    try:
        return _run_market_analysis(request.model_dump())
    except Exception:
        logger.exception("Market analysis error")
        raise HTTPException(status_code=500, detail="Error analyzing market trends")

@app.post("/analyze/transition")
async def analyze_transition(request: TransitionRequest, http_request: Request):
    try:
        orchestrator = _get_agent_orchestrator(http_request)
        current_role = str(request.profile.get("role") or settings.default_role_title)
        current_skills = [str(skill) for skill in request.profile.get("skills", []) if str(skill).strip()]
        skill_gap_context = request.skill_gap_context or None
        if skill_gap_context:
            current_skills = skill_gap_context.get("skill_analysis", {}).get("matched_skills", []) + [
                item.get("skill", "") for item in skill_gap_context.get("skill_analysis", {}).get("skill_gaps", [])
            ]
            current_skills = [s for s in current_skills if s]
        analysis = orchestrator.career_agent.analyze_transition(
            skill_gap_context or current_role,
            target_role=request.target_role,
            current_skills=current_skills,
            user_profile={**request.profile, "current_role": current_role, "target_role": request.target_role},
        )
        feasibility = analysis.get("feasibility_analysis", {})

        return {
            "transition_score": feasibility.get("transition_score", 0.0),
            "target_role_gaps": feasibility.get("critical_gaps", []),
            "matched_skills": feasibility.get("matched_skills_count", 0),
            "expected_skills": feasibility.get("skills_to_develop", 0),
            "details": analysis,
        }
    except Exception:
        logger.exception("Transition analysis error")
        raise HTTPException(status_code=500, detail="Error analyzing transition")

@app.post("/generate/roadmap")
async def generate_roadmap(request: RoadmapRequest, http_request: Request):
    try:
        skill_gap_payload = getattr(request, "skill_gap", None)
        logger.info(
            "[ROADMAP GENERATION] Received request: skill_gap=%s, target_role=%s",
            skill_gap_payload,
            request.target_role,
        )
        orchestrator = _get_agent_orchestrator(http_request)

        skill_gap = skill_gap_payload if skill_gap_payload is not None else {}
        if not skill_gap and request.gaps:
            skill_gap = {"core_gaps": request.gaps}
        if not skill_gap:
            skill_gap = {}
        if isinstance(skill_gap, list):
            skill_gap = {"core_gaps": skill_gap}

        roadmap = orchestrator.learning_agent.generate_learning_roadmap(
            skill_gap,
            target_role=request.target_role or None,
        )

        # ✅ Extract user email from session FIRST
        user_json = http_request.session.get("siemens_user")
        user_email = None
        user_id = None
        if user_json:
            user = json.loads(user_json) if isinstance(user_json, str) else user_json
            user_email = user.get("email")
            user_id = user.get("id")

        # ✅ Generate user-specific slug
        slug = _roadmap_slug_from(roadmap, user_email=user_email)

        # ✅ Patch the slug back into the roadmap payload so frontend receives it
        if "metadata" not in roadmap or not isinstance(roadmap.get("metadata"), dict):
            roadmap["metadata"] = {}
        roadmap["metadata"]["roadmap_slug"] = slug

        try:
            _persist_generated_roadmap_snapshot(roadmap)
        except Exception:
            logger.exception("Failed to persist generated roadmap snapshot")

        # ✅ Store in memory store with user-specific slug
        _roadmap_store[slug] = roadmap
        roadmap_id = str(roadmap.get("roadmap_id", "")).strip()
        if roadmap_id and roadmap_id != slug:
            _roadmap_store[roadmap_id] = roadmap

        postgres_service = _get_postgres_service(http_request)
        if postgres_service is not None:
            try:
                # ✅ Pass user_email to sync so nodes are user-scoped
                stored_count = postgres_service.sync_roadmap_nodes(
                    roadmap,
                    user_email=user_email
                )
                logger.info(
                    "[ROADMAP GENERATION] Synced nodes: count=%s slug=%s user=%s",
                    stored_count, slug, user_email,
                )

                try:
                    _allocate_node_videos(postgres_service, roadmap)
                except Exception:
                    logger.exception("Failed to allocate videos for roadmap=%s", slug)

                # ✅ Store roadmap with both user_id and user_email
                if user_id:
                    postgres_service.store_user_roadmap(
                        user_id=user_id,
                        roadmap_slug=slug,
                        user_email=user_email       # ← NEW
                    )
                    logger.info(
                        "[ROADMAP GENERATION] Stored slug '%s' for user_id=%s email=%s",
                        slug, user_id, user_email
                    )
            except Exception:
                logger.exception("Failed to sync roadmap nodes for slug=%s", slug)

        return roadmap

    except Exception:
        logger.exception("Roadmap generation error")
        raise HTTPException(status_code=500, detail="Error generating roadmap")

# â”€â”€ Roadmap progress & node endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/roadmap/progress")
async def get_roadmap_progress(roadmap_slug: str, user_id: str, request: Request):
    """
    Return overall completion stats for a roadmap + user.

    Query params:
      roadmap_slug  â€“ value from roadmap.metadata.roadmap_slug or roadmap.roadmap_id
      user_id       â€“ current user identifier
    """
    postgres_service = _get_postgres_service(request)
    
    if postgres_service is not None:
        try:
            db_payload = postgres_service.get_roadmap_progress_from_db(
                roadmap_slug=roadmap_slug,
                user_id=user_id,
            )
            if db_payload.get("total", 0) > 0:
                return db_payload
        except Exception:
            logger.exception("Failed to fetch roadmap progress from DB for slug=%s", roadmap_slug)

    roadmap = _roadmap_store.get(roadmap_slug)
    if not roadmap:
        # Try a prefix match so partial slugs still resolve
        for key, value in _roadmap_store.items():
            if roadmap_slug in key or key in roadmap_slug:
                roadmap = value
                roadmap_slug = key
                break

    if not roadmap:
        # Return zeroed progress rather than a hard 404 so the UI doesn't crash
        return {
            "roadmap_slug": roadmap_slug,
            "user_id": user_id,
            "total": 0,
            "completed": 0,
            "in_progress": 0,
            "not_started": 0,
            "completion_rate": 0.0,
        }

    return _compute_progress(roadmap, user_id, roadmap_slug)

@app.get("/roadmap/skills")
async def get_roadmap_skills(roadmap_slug: str, user_id: str, request: Request):
    """
    Return per-skill node lists with live status for the roadmap viewer.

    Query params:
      roadmap_slug  â€“ value from roadmap.metadata.roadmap_slug or roadmap.roadmap_id
      user_id       â€“ current user identifier

    Response shape:
      { roadmap_slug, user_id, skills: [ { skill, total, completed, nodes: [...] } ] }
    """
    postgres_service = _get_postgres_service(request)
    
    if postgres_service is not None:
        try:
            db_payload = postgres_service.get_roadmap_skills_from_db(
                roadmap_slug=roadmap_slug,
                user_id=user_id,
                node_status_overrides=_node_status_store,
            )
            if db_payload.get("skills"):
                return db_payload
        except Exception:
            logger.exception("Failed to fetch roadmap skills from DB for slug=%s", roadmap_slug)

    roadmap = _roadmap_store.get(roadmap_slug)
    if not roadmap:
        for key, value in _roadmap_store.items():
            if roadmap_slug in key or key in roadmap_slug:
                roadmap = value
                roadmap_slug = key
                break

    if not roadmap:
        return {"roadmap_slug": roadmap_slug, "user_id": user_id, "skills": []}

    skill_rows = _build_skill_rows(roadmap, user_id, roadmap_slug)
    return {
        "roadmap_slug": roadmap_slug,
        "user_id": user_id,
        "skills": skill_rows,
    }

@app.get("/roadmap/nodes/{node_id}/resources")
async def get_node_resources(node_id: str, user_id: str, request: Request):
    """
    Return details and learning resources for a single roadmap node.

    Path param : node_id  â€“ prefixed node id e.g. "python--variables--basics"
    Query param: user_id  â€“ current user identifier

    Response shape:
      { node_id, title, type, category, phase_title, user_status, resources: { videos: [...] } }
    """
    # Try DB first, then fallback to memory
    postgres_service = _get_postgres_service(request)
    found_node: Optional[Dict[str, Any]] = None
    found_phase_title = ""
    found_roadmap_slug = ""
    
    if postgres_service is not None:
        try:
            conn = postgres_service.engine.connect()
            row = conn.execute(
                __import__('sqlalchemy').text(
                    """
                    SELECT rn.node_id, rn.source_node_id, rn.title, rn.node_type, rn.phase_title, rn.category, rn.raw_node, rn.roadmap_slug
                    FROM roadmap_nodes rn
                    WHERE rn.node_id = :node_id
                    LIMIT 1
                    """
                ),
                {"node_id": node_id},
            ).fetchone()
            conn.close()
            if row:
                found_node = {
                    "node_id": row.node_id,
                    "source_node_id": row.source_node_id,
                    "title": row.title,
                    "type": row.node_type,
                    "category": row.category,
                    "phase_title": row.phase_title,
                }
                raw_node = row.raw_node if isinstance(row.raw_node, dict) else {}
                if isinstance(raw_node, dict):
                    found_node.update(raw_node)
                found_roadmap_slug = str(row.roadmap_slug)
        except Exception:
            logger.exception("Failed to fetch node from DB for node_id=%s", node_id)

    # Fallback to in-memory roadmaps if DB lookup failed
    if not found_node:
        for slug, roadmap in _roadmap_store.items():
            for phase in roadmap.get("phases", []):
                for node in phase.get("nodes", []):
                    if str(node.get("node_id", "")) == node_id:
                        found_node = node
                        found_phase_title = str(phase.get("phase_title", ""))
                        found_roadmap_slug = slug
                        break
                if found_node:
                    break
            if found_node:
                break

    if not found_node:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found in any stored roadmap.")

    store_key = f"{found_roadmap_slug}:{user_id}:{node_id}"
    user_status = _node_status_store.get(store_key) or found_node.get("status") or "not_started"
    
    # Fetch videos from DB. If none are mapped yet, backfill on-demand for this node.
    videos: list[dict[str, Any]] = []
    lookup_node_id = str(
        found_node.get("source_node_id")
        or found_node.get("original_node_id")
        or found_node.get("node_id")
        or node_id
    ).strip()
    effective_slug = found_roadmap_slug or "generated"

    if postgres_service is not None:
        query_seed = {
            "node_id": node_id,
            "source_roadmap": found_node.get("source_roadmap"),
            "label": found_node.get("label") or found_node.get("title"),
            "title": found_node.get("title"),
            "matched_skill": found_node.get("matched_skill"),
        }
        candidate_queries = _build_node_video_queries(query_seed, lookup_node_id or node_id)

        try:
            videos = postgres_service.get_node_videos(
                effective_slug,
                node_id,
                lookup_node_id=lookup_node_id,
            )
            videos = _filter_relevant_videos(videos, candidate_queries)
        except Exception:
            logger.exception("Failed to fetch videos for node_id=%s roadmap=%s", node_id, effective_slug)

        if not videos:
            youtube_enabled, youtube_reason = validate_youtube_api_key()
            auth_error_logged = False
            try:
                for query in candidate_queries:
                    fresh_videos: list[dict[str, Any]] = []
                    if youtube_enabled:
                        try:
                            api_results = fetch_videos(query, max_results=5)
                            fresh_videos = _filter_relevant_videos(format_videos(api_results), candidate_queries)
                        except YouTubeAuthError:
                            youtube_enabled = False
                            if not auth_error_logged:
                                logger.warning(
                                    "[RESOURCE ALLOCATION] YouTube API authorization failed; using catalog fallback for node resources"
                                )
                                auth_error_logged = True
                        except YouTubeClientError as exc:
                            logger.warning(
                                "[RESOURCE ALLOCATION] Live YouTube fetch failed for node=%s query='%s' (%s); trying catalog fallback",
                                node_id,
                                query,
                                exc,
                            )
                    elif query == candidate_queries[0]:
                        logger.info(
                            "[RESOURCE ALLOCATION] Live YouTube fetch skipped for node=%s (%s)",
                            node_id,
                            youtube_reason,
                        )

                    if not fresh_videos:
                        fresh_videos = _filter_relevant_videos(
                            postgres_service.search_videos_catalog(query, limit=5),
                            candidate_queries,
                        )

                    if not fresh_videos:
                        continue

                    postgres_service.upsert_node_videos(effective_slug, node_id, fresh_videos)
                    videos = postgres_service.get_node_videos(
                        effective_slug,
                        node_id,
                        lookup_node_id=lookup_node_id,
                    )
                    if videos:
                        logger.info(
                            "[RESOURCE ALLOCATION] Backfilled %d videos for node=%s using query='%s'",
                            len(videos),
                            node_id,
                            query,
                        )
                        break
            except Exception:
                logger.exception("On-demand video backfill failed for node_id=%s", node_id)

    # ── Fallback: try YouTube web search parsing (no API key), then links ───
    if not videos:
        node_title = str(found_node.get("label") or found_node.get("title") or node_id).strip()
        skill_hint = str(found_node.get("matched_skill") or "").strip()
        search_terms = [
            f"{node_title} tutorial",
            f"{skill_hint} {node_title}" if skill_hint and skill_hint.lower() not in node_title.lower() else None,
            f"{skill_hint} for beginners" if skill_hint else None,
        ]

        # Try to get concrete video IDs + thumbnails from public YouTube search page.
        for term in (t for t in search_terms if t):
            try:
                inferred_videos = fetch_videos_from_search_page(term, max_results=2)
            except YouTubeClientError:
                inferred_videos = []
            if inferred_videos:
                videos.extend(inferred_videos)
                break

    # Final fallback: plain search links only when concrete videos are unavailable.
    if not videos:
        node_title = str(found_node.get("label") or found_node.get("title") or node_id).strip()
        skill_hint = str(found_node.get("matched_skill") or "").strip()
        search_terms = [
            f"{node_title} tutorial",
            f"{skill_hint} {node_title}" if skill_hint and skill_hint.lower() not in node_title.lower() else None,
            f"{skill_hint} for beginners" if skill_hint else None,
        ]
        for i, term in enumerate(t for t in search_terms if t):
            encoded = term.replace(" ", "+")
            videos.append({
                "video_id": None,
                "title": f"Search: {term}",
                "channel": "YouTube Search",
                "thumbnail": None,
                "youtube_url": f"https://www.youtube.com/results?search_query={encoded}",
                "score": 0,
                "is_search_link": True,
            })
            if i >= 1:  # keep to 2 search links max
                break

    return {
        "node_id": node_id,
        "source_node_id": found_node.get("source_node_id") or found_node.get("original_node_id") or node_id,
        "title": found_node.get("label") or found_node.get("title") or node_id,
        "type": found_node.get("type", "topic"),
        "phase_id": found_node.get("phase_id"),
        "phase_title": found_phase_title or found_node.get("phase_title"),
        "category": found_node.get("category"),
        "roadmap_slug": found_roadmap_slug,
        "importance": found_node.get("importance"),
        "matched_skill": found_node.get("matched_skill"),
        "source_roadmap": found_node.get("source_roadmap"),
        "depends_on": found_node.get("depends_on", []),
        "user_status": user_status,
        "resources": {
            "type": "youtube",
            "total": len(videos),
            "videos": videos,
        },
    }
@app.patch("/roadmap/nodes/{node_id}/status")
async def update_node_status(
    node_id: str,
    user_id: str,
    body: NodeStatusRequest,
    request: Request,
    roadmap_slug: Optional[str] = None,
):
    found_slug = str(roadmap_slug or "").strip()
    postgres_service = _get_postgres_service(request)

    logger.info(
        "[NODE STATUS] PATCH request: node=%s, user_id=%s, roadmap_slug=%s, status=%s",
        node_id, user_id, found_slug, body.status,
    )

    # ✅ Step 1 — DB lookup WITH user_id filter
    if postgres_service is not None:
        try:
            conn = postgres_service.engine.connect()

            if found_slug and found_slug != "generated":
                row = conn.execute(
                    text(
                        """
                        SELECT roadmap_slug FROM roadmap_nodes
                        WHERE node_id = :node_id AND roadmap_slug = :slug
                        LIMIT 1
                        """
                    ),
                    {"node_id": node_id, "slug": found_slug},
                ).fetchone()
            else:
                # ✅ FIXED: filter by user_id pattern so naveen gets naveen's slug
                row = conn.execute(
                    text(
                        """
                        SELECT roadmap_slug FROM roadmap_nodes
                        WHERE node_id    = :node_id
                          AND roadmap_slug ILIKE :user_pattern
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """
                    ),
                    {
                        "node_id": node_id,
                        "user_pattern": f"%{user_id.replace('@', '-at-').replace('.', '-')}%",
                    },
                ).fetchone()

            conn.close()

            if row:
                found_slug = row.roadmap_slug
                logger.info("[NODE STATUS] Found node in DB with roadmap_slug=%s", found_slug)

        except Exception as e:
            logger.warning("[NODE STATUS] DB node lookup failed: %s", e)

    # ✅ Step 2 — Memory store fallback WITH user_id filter
    if not found_slug or found_slug == "generated":
        found = False
        # ✅ Check user-scoped slug first
        user_pattern = user_id.replace("@", "-at-").replace(".", "-")
        for slug, roadmap in _roadmap_store.items():
            if user_pattern not in slug:          # ← skip other users' roadmaps
                continue
            for phase in roadmap.get("phases", []):
                for node in phase.get("nodes", []):
                    if str(node.get("node_id", "")) == node_id:
                        found = True
                        found_slug = slug
                        logger.info("[NODE STATUS] Found node in memory with roadmap_slug=%s", found_slug)
                        break
                if found:
                    break
            if found:
                break

    # ✅ Step 3 — Last resort fallback
    if not found_slug:
        found_slug = roadmap_slug or "generated"
        logger.warning(
            "[NODE STATUS] Node not found in DB or memory, using fallback slug: %s", found_slug
        )

    # ✅ Step 4 — Persist with correct slug
    updated = False
    if postgres_service is not None and found_slug:
        try:
            updated = postgres_service.upsert_node_progress(found_slug, user_id, node_id, body.status)
            logger.info(
                "[NODE STATUS] Persisted to DB: slug=%s, node=%s, updated=%s",
                found_slug, node_id, updated,
            )
        except Exception as e:
            logger.exception("[NODE STATUS] Failed to persist to DB: %s", e)

    # Memory store
    store_key = f"{found_slug}:{user_id}:{node_id}"
    _node_status_store[store_key] = body.status

    # ✅ Step 5 — Skill promotion
    promoted_skill: Optional[str] = None
    if body.status == "completed" and postgres_service is not None and found_slug:
        try:
            promoted_skill = postgres_service.check_and_promote_skill(found_slug, user_id, node_id)
            if promoted_skill:
                logger.info(
                    "[SKILL PROMOTE] Skill '%s' promoted for user=%s",
                    promoted_skill, user_id,
                )
        except Exception:
            logger.exception("[SKILL PROMOTE] Failed for node=%s user=%s", node_id, user_id)

    return {
        "node_id": node_id,
        "user_id": user_id,
        "status": body.status,
        "updated": updated,          # ✅ real value, not hardcoded True
        "promoted_skill": promoted_skill,
    }
# â”€â”€ Talent matching â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.post("/talent/match")
async def match_talent(request: JobDescriptionRequest, http_request: Request):
    try:
        postgres_service = _get_postgres_service(http_request)
        if postgres_service is None:
            raise HTTPException(
                status_code=503,
                detail="Database unavailable. Configure DATABASE_URL to enable talent matching.",
            )
        employees = postgres_service.get_employee_profiles()
        llm_client = _get_llm_client(http_request)
        agent = TalentAgent(
            employee_repo=employees,
            llm_client=llm_client.client if llm_client else None,
            skill_catalog=settings.skill_catalog,
            max_matches=settings.max_talent_matches,
        )
        result = await asyncio.wait_for(
        asyncio.to_thread(agent.match_employees, request.job_description[:10000]),
        timeout=60.0  # fail after 60 seconds
)
        matches = result if isinstance(result, list) else result.get("matches", [])
        required_skills = [] if isinstance(result, list) else result.get("required_skills", [])

        normalized_matches = [
            {
                "id": m.get("id"),
                "name": m.get("name", "Unknown"),
                "match_percentage": float(m.get("match_percentage", 0.0) or 0.0),
                "matched_skills": m.get("matched_skills", []),
                "missing_skills": m.get("missing_skills", []),
                "total_required": int(m.get("total_required", len(required_skills)) or 0),
                "total_matched": int(m.get("total_matched", 0) or 0),
            }
            for m in matches
        ]

        return {
            "status": "success",
            "job_required_skills": required_skills,
            "total_candidates": len(employees),
            "matches": normalized_matches,
            "rankings": normalized_matches,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Talent matching error")
        raise HTTPException(status_code=500, detail="Error in talent matching")

@app.post("/workflow/manager")
async def run_manager_workflow(request: ManagerWorkflowRequest, http_request: Request):
    try:
        postgres_service = _get_postgres_service(http_request)
        if postgres_service is None:
            raise HTTPException(status_code=503, detail="Database unavailable.")

        employees = postgres_service.get_employee_profiles()

        if not employees:
            raise HTTPException(status_code=404, detail="No employee profiles found.")

        llm_client = _get_llm_client(http_request)
        agent = TalentAgent(
            employee_repo=employees,
            llm_client=llm_client.client if llm_client else None,
            skill_catalog=settings.skill_catalog,
            max_matches=settings.max_talent_matches,
        )

        result = agent.match_employees(request.job_description[:10000])
        matches = result if isinstance(result, list) else result.get("matches", [])
        required_skills = [] if isinstance(result, list) else result.get("required_skills", [])

        normalized_matches = [
            {
                "id": m.get("id"),
                "name": m.get("name", "Unknown"),
                "match_percentage": float(m.get("match_percentage", 0.0) or 0.0),
                "matched_skills": m.get("matched_skills", []),
                "missing_skills": m.get("missing_skills", []),
                "total_required": int(m.get("total_required", len(required_skills)) or 0),
                "total_matched": int(m.get("total_matched", 0) or 0),
            }
            for m in matches
        ]

        matched_users_count = sum(
            1 for match in normalized_matches if match["match_percentage"] > 0
        )
        total_candidates = len(employees)
        matched_users_percentage = round(
            (matched_users_count / total_candidates) * 100, 2
        ) if total_candidates else 0.0

        return {
            "status":              "success",
            "pipeline_complete":   True,
            "job_required_skills": required_skills,
            "total_candidates":    total_candidates,
            "matched_users_count": matched_users_count,
            "matched_users_percentage": matched_users_percentage,
            "matches":             normalized_matches,
            "learning_resources": {
                "matches": normalized_matches,
            },
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Manager workflow error")
        raise HTTPException(status_code=500, detail="Error running manager workflow")


@app.post("/workflow/employee")
async def run_employee_workflow(request: EmployeeWorkflowRequest, http_request: Request):
    try:
        orchestrator = _get_agent_orchestrator(http_request)
        text = request.resume_text[:5000]
        profile = _extract_profile_from_text(orchestrator, text)

        target_role = str(request.target_role or profile.get("role") or settings.default_role_title)
        profile["target_role"] = target_role
        current_skills = [str(skill) for skill in profile.get("skills", []) if str(skill).strip()]

        skill_analysis = orchestrator.skill_agent.analyze_skills(
            current_skills,
            target_role,
            user_profile=profile,
        )

        market = _run_market_analysis(profile)
        gaps = skill_analysis.get("core_gaps", [])[: settings.max_core_gaps]
        roadmap = orchestrator.learning_agent.generate_learning_roadmap(
            {"core_gaps": gaps},
            current_skills,
            target_role,
            "balanced",
        )

        return {
            "status": "success",
            "profile": profile,
            "readiness_score": skill_analysis.get("readiness_summary", {}).get("readiness_score", 0),
            "core_gaps": gaps,
            "market_gaps": market.get("market_gaps", []),
            "roadmap": roadmap,
        }
    except Exception:
        logger.exception("Employee workflow error")
        raise HTTPException(status_code=500, detail="Error running employee workflow")
    

class CompletePipelineRequest(BaseModel):
    """Request for complete LangGraph agent pipeline."""
    pdf_path: Optional[str] = Field(default=None, description="Path to resume PDF or None to use resume_text")
    resume_text: Optional[str] = Field(default=None, description="Resume as text")
    target_role: Optional[str] = Field(default=None, description="Target role for analysis")
    learning_style: str = Field(default="balanced", description="Learning style: theory, practice, or balanced")


class LoginRequest(BaseModel):
    email: str = Field(default="")
    password: str = Field(default="")
    siemens_id: str = Field(default="")
    name: str = Field(default="")
    department: str = Field(default="")
    role: str = Field(default="")
    experience_years: int = Field(default=0)
    skills: List[str] = Field(default_factory=list)


class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    department: Optional[str] = None
    role: Optional[str] = None
    experience_years: Optional[int] = None
    skills: Optional[List[str]] = None


@app.post("/pipeline/complete")
async def run_complete_langgraph_pipeline(request: CompletePipelineRequest, http_request: Request):
    """
    Complete LangGraph agent pipeline demonstrating all agents working together.
    
    Shows:
    - Resume Agent: Extracts profile from PDF/text
    - Skill Agent: Analyzes skills and identifies gaps
    - Career Agent: Plans career transitions
    - Learning Agent: Generates learning roadmap
    
    Each agent runs independently with explicit tools and reasoning loops.
    """
    try:
        orchestrator = _get_agent_orchestrator(http_request)
        if not request.pdf_path and not request.resume_text:
            raise HTTPException(status_code=400, detail="Provide either pdf_path or resume_text")

        if request.pdf_path:
            result = orchestrator.process_resume_and_analyze(
                pdf_path=request.pdf_path,
                target_role=request.target_role,
                learning_style=request.learning_style,
            )
        else:
            text = request.resume_text[:5000]
            profile_extractor = orchestrator.resume_agent.tools.profile_extractor
            profile = {
                "role": profile_extractor.extract_role(text),
                "experience": profile_extractor.extract_experience(text),
                "skills": profile_extractor.extract_skills(text),
                "education": profile_extractor.extract_education(profile_extractor._split_lines(text)),
            }

            current_role = profile.get("role", "Software Developer")
            current_skills = profile.get("skills", [])
            target_role = request.target_role or current_role
            skill_analysis = orchestrator.skill_agent.analyze_skills(
                current_skills,
                target_role,
                user_profile=profile,
            )
            skill_gaps = list(dict.fromkeys(
                skill_analysis.get("core_gaps", [])
                + [item.get("skill", "") for item in skill_analysis.get("skill_analysis", {}).get("skill_gaps", [])]
            ))
            career_analysis = orchestrator.career_agent.analyze_transition(
                skill_analysis,
                current_skills=current_skills,
                user_profile={
                    "current_role": current_role,
                    "target_role": target_role,
                    "experience_years": profile.get("experience", 0),
                },
            )
            learning_roadmap = orchestrator.learning_agent.generate_learning_roadmap(
                skill_gaps,
                current_skills,
                target_role,
                request.learning_style,
            )

            result = {
                "profile": {
                    "role": current_role,
                    "experience_years": profile.get("experience", 0),
                    "current_skills": current_skills,
                    "education": profile.get("education", []),
                },
                "skill_analysis": skill_analysis,
                "career_analysis": career_analysis,
                "learning_roadmap": learning_roadmap,
                "pipeline_status": "complete",
            }
        
        # Add explanation of agent reasoning
        explanation = orchestrator.explain_agent_reasoning(result)
        
        return {
            "status": "success",
            "pipeline_complete": True,
            "analysis": result,
            "agent_reasoning": explanation,
        }
    except Exception as e:
        logger.error(f"Complete pipeline error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")


@app.get("/agents/info")
async def get_agents_info():
    """
    Get information about available agents and their tools.
    """
    return {
        "agents": {
            "resume_agent": {
                "description": "Extracts profile information from resumes",
                "tools": [
                    "extract_text_from_pdf",
                    "extract_text_from_pdf_bytes",
                    "extract_role_from_resume",
                    "extract_experience_from_resume",
                    "extract_skills_from_resume",
                    "extract_education_from_resume",
                    "normalize_skills",
                ],
                "type": "LangGraph State Machine",
                "reasoning_type": "Sequential extraction with validation",
            },
            "skill_agent": {
                "description": "Analyzes skills and identifies gaps",
                "tools": [
                    "get_expected_skills_for_role",
                    "find_skill_gaps",
                    "rank_skills_by_importance",
                ],
                "type": "LangGraph State Machine",
                "reasoning_type": "Think-Act-Observe-Reflect cycles",
            },
            "career_agent": {
                "description": "Plans career transitions and explores paths",
                "tools": [
                    "analyze_transition_feasibility",
                    "identify_career_path_options",
                    "estimate_transition_timeline",
                ],
                "type": "LangGraph State Machine",
                "reasoning_type": "Think-Act-Reflect with alternatives",
            },
            "learning_agent": {
                "description": "Generates structured learning roadmaps",
                "tools": [
                    "generate_learning_path",
                    "create_project_based_roadmap",
                    "suggest_learning_resources",
                ],
                "type": "LangGraph State Machine",
                "reasoning_type": "Structured planning with multiple phases",
            },
            "market_agent": {
                "description": "Analyzes market trends and skill lifecycle",
                "tools": [
                    "collect_emerging_skills",
                    "classify_skill_lifecycle",
                    "compute_market_gaps",
                ],
                "type": "LangGraph State Machine",
                "reasoning_type": "Signal collection and lifecycle classification",
            },
            "talent_agent": {
                "description": "Extracts JD skills and ranks candidate profiles",
                "tools": [
                    "extract_required_skills",
                    "rank_employees",
                ],
                "type": "LangGraph State Machine",
                "reasoning_type": "Think-Extract-Rank pipeline",
            },
        },
        "architecture": {
            "framework": "LangGraph with LangChain",
            "tool_definition": "Explicit tool modules with schema-driven methods",
            "agentic_behavior": "True agents with reason-act-observe-reflect cycles",
            "orchestration": "Sequential pipeline with tool-based reasoning",
        },
    }


@app.get("/health")
async def health_check(request: Request):
    postgres_service = _get_postgres_service(request)
    db_status = "up" if postgres_service and postgres_service.ping() else "down"
    status = "healthy" if db_status == "up" else "degraded"
    warnings = _configuration_warnings()
    return {
        "status": status,
        "database": db_status,
        "environment": settings.app_env,
        "config_warnings": warnings,
    }


@app.post("/api/auth/login")
async def auth_login(request: Request, body: LoginRequest):
    try:
        postgres_service = _get_postgres_service(request)
        if postgres_service is None:
            raise HTTPException(status_code=503, detail="Database unavailable")

        profile_payload: dict[str, Any] = {
            "email": body.email or f"user_{uuid.uuid4().hex[:8]}@siemens.com",
            "siemens_id": body.siemens_id,
            "name": body.name,
            "department": body.department,
            "role": body.role,
            "experience_years": body.experience_years,
            "skills": body.skills or [],
        }

        saved = postgres_service.upsert_user_profile(profile_payload)
        token = f"siemens_{saved['id']}_{uuid.uuid4().hex[:16]}"
        request.session["siemens_auth"] = True
        request.session["siemens_user"] = json.dumps(saved)
        request.session["siemens_token"] = token
        return {
            "status": "success",
            "user": saved,
            "token": token,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Login error")
        raise HTTPException(status_code=500, detail="Login failed")


@app.get("/signup", response_class=HTMLResponse)
async def serve_signup():
    signup_html_path = PROJECT_ROOT / "frontend" / "public" / "signup.html"
    if signup_html_path.exists():
        return HTMLResponse(content=signup_html_path.read_text(encoding="utf-8-sig"))
    raise HTTPException(status_code=404, detail="Signup page not found")


@app.get("/login", response_class=HTMLResponse)
async def serve_siemens_login():
    login_html_path = PROJECT_ROOT / "frontend" / "public" / "siemens-login.html"
    if login_html_path.exists():
        return HTMLResponse(content=login_html_path.read_text(encoding="utf-8-sig"))
    raise HTTPException(status_code=404, detail="Login page not found")


class SiemensLoginRequest(BaseModel):
    username: str = Field(default="")
    password: str = Field(default="")


class SignupRequest(BaseModel):
    email: str = Field(default="")
    password: str = Field(default="")
    name: str = Field(default="")
    department: str = Field(default="")
    role: str = Field(default="")
    experience_years: int = Field(default=0)
    skills: list[str] = Field(default_factory=list)


@app.post("/api/auth/signup")
async def signup(request: Request, body: SignupRequest):
    try:
        postgres_service = _get_postgres_service(request)
        if postgres_service is None:
            raise HTTPException(status_code=503, detail="Database unavailable")

        email = body.email.strip()
        if not email or not body.password:
            raise HTTPException(status_code=400, detail="Email and password are required")

        existing = postgres_service.get_user_by_email(email)
        if existing:
            raise HTTPException(status_code=409, detail="User with this email already exists")

        user = postgres_service.create_user(
            email=email,
            password=body.password,
            name=body.name,
            department=body.department,
            role=body.role,
            experience_years=body.experience_years,
            skills=body.skills,
        )

        user_data = {
            "id": user.id,
            "email": user.email,
            "siemens_id": user.siemens_id,
            "name": user.name,
            "department": user.department,
            "role": user.role,
            "experience_years": user.experience_years,
            "skills": user.skills,
        }

        token = f"siemens_{user.id}_{uuid.uuid4().hex[:16]}"
        request.session["siemens_auth"] = True
        request.session["siemens_user"] = json.dumps(user_data)
        request.session["siemens_token"] = token

        return {
            "status": "success",
            "user": user_data,
            "token": token,
            "needs_profile": False,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Signup error")
        raise HTTPException(status_code=500, detail="Signup failed")


@app.post("/api/auth/siemens-login")
async def siemens_login(request: Request, body: SiemensLoginRequest):
    try:
        postgres_service = _get_postgres_service(request)
        if postgres_service is None:
            raise HTTPException(status_code=503, detail="Database unavailable")

        email = body.username.strip()
        password = body.password

        if not email:
            raise HTTPException(status_code=400, detail="Email is required")

        user = postgres_service.get_user_by_email(email)
        if not user:
            user = postgres_service.get_user_by_siemens_id(email)

        if not user or not verify_password(password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        user_data = {
            "id": user.id,
            "email": user.email,
            "siemens_id": user.siemens_id,
            "name": user.name,
            "department": user.department,
            "role": user.role,
            "experience_years": user.experience_years,
            "skills": user.skills,
        }

        token = f"siemens_{user.id}_{uuid.uuid4().hex[:16]}"
        request.session["siemens_auth"] = True
        request.session["siemens_user"] = json.dumps(user_data)
        request.session["siemens_token"] = token

        return {
            "status": "success",
            "user": user_data,
            "token": token,
            "needs_profile": not user.name or not user.role,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Login error")
        raise HTTPException(status_code=500, detail="Login failed")


@app.get("/profile-creation", response_class=HTMLResponse)
async def serve_profile_creation():
    profile_html_path = PROJECT_ROOT / "frontend" / "public" / "profile-creation.html"
    if profile_html_path.exists():
        return HTMLResponse(content=profile_html_path.read_text(encoding="utf-8-sig"))
    raise HTTPException(status_code=404, detail="Profile creation page not found")


@app.get("/api/auth/me")
async def auth_me(request: Request):
    if not request.session.get("siemens_auth"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_json = request.session.get("siemens_user")
    if not user_json:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = json.loads(user_json) if isinstance(user_json, str) else user_json
    return {"status": "success", "user": user}


@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    request.session.pop("siemens_auth", None)
    request.session.pop("siemens_user", None)
    request.session.pop("siemens_token", None)
    return {"status": "success", "message": "Logged out"}


@app.get("/api/user/profile")
async def get_user_profile(request: Request):
    try:
        postgres_service = _get_postgres_service(request)
        if postgres_service is None:
            raise HTTPException(status_code=503, detail="Database unavailable")

        if not request.session.get("siemens_auth"):
            raise HTTPException(status_code=401, detail="Not authenticated")

        user_json = request.session.get("siemens_user")
        if not user_json:
            raise HTTPException(status_code=401, detail="Not authenticated")

        user = json.loads(user_json) if isinstance(user_json, str) else user_json
        siemens_id = user.get("siemens_id")
        email = user.get("email")

        profile = None
        if siemens_id:
            profile = postgres_service.get_user_profile_by_siemens_id(siemens_id)
        if not profile and email:
            profile = postgres_service.get_user_profile_by_email(email)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")

        return {"status": "success", "profile": profile}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Profile fetch error")
        raise HTTPException(status_code=500, detail="Error fetching profile")


@app.put("/api/user/profile")
async def update_user_profile(request: Request, body: ProfileUpdateRequest):
    try:
        postgres_service = _get_postgres_service(request)
        if postgres_service is None:
            raise HTTPException(status_code=503, detail="Database unavailable")

        if not request.session.get("siemens_auth"):
            raise HTTPException(status_code=401, detail="Not authenticated")

        user_json = request.session.get("siemens_user")
        if not user_json:
            raise HTTPException(status_code=401, detail="Not authenticated")

        user = json.loads(user_json) if isinstance(user_json, str) else user_json
        update_payload: dict[str, Any] = {}
        for field in ("name", "department", "role", "experience_years", "skills"):
            val = getattr(body, field)
            if val is not None:
                update_payload[field] = val
        update_payload["email"] = user.get("email", "")
        update_payload["siemens_id"] = user.get("siemens_id", "")

        saved = postgres_service.upsert_user_profile(update_payload)
        request.session["siemens_user"] = json.dumps(saved)
        return {"status": "success", "profile": saved}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Profile update error")
        raise HTTPException(status_code=500, detail="Error updating profile")