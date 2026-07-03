"""Career Transition Agent using LangGraph and LangChain."""
import logging
import json
import os
import re
import sys
import random
import importlib
from typing import TypedDict, List, Optional, Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from src.config import settings
from src.tools.career_tools import CareerTools
from src.models.career_schema import CareerAgentOutputSchema

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ══════════════════════════════════════════════════════════════════════════════
#  BM25 IMPORT WITH FALLBACK
# ══════════════════════════════════════════════════════════════════════════════

_rank_bm25_module = importlib.import_module("rank_bm25") if importlib.util.find_spec("rank_bm25") else None
if _rank_bm25_module is not None:
    BM25Okapi = _rank_bm25_module.BM25Okapi
else:
    class BM25Okapi:
        """Fallback scorer used when rank_bm25 is unavailable."""
        def __init__(self, corpus: list):
            self.corpus = corpus

        def get_scores(self, query_tokens: list) -> list:
            query_set = set(query_tokens)
            scores = []
            for doc in self.corpus:
                if not doc:
                    scores.append(0.0)
                    continue
                doc_set = set(doc)
                overlap = len(query_set & doc_set)
                scores.append(float(overlap))
            return scores

# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

LEVEL_STR_TO_INT: dict = {
    "beginner"    : 1,
    "basic"       : 1,
    "intermediate": 2,
    "advanced"    : 3,
    "expert"      : 4,
}

LEVEL_INT_TO_STR: dict = {
    0: "none",
    1: "beginner",
    2: "intermediate",
    3: "advanced",
    4: "expert",
}

# Weighted random level distribution for user skill initialization
# Skewed toward intermediate/advanced to be realistic
LEVEL_POOL: list = [
    "beginner",
    "beginner",
    "intermediate",
    "intermediate",
    "intermediate",
    "advanced",
    "advanced",
    "expert",
]

BM25_MATCH_THRESHOLD: float = 1.0

PRIORITY_ORDER: dict = {
    "critical": 1,
    "high"    : 2,
    "medium"  : 3,
    "low"     : 4,
}

READINESS_CATEGORIES: list = [
    (85.0, "role_ready",    "You are ready for this role!"),
    (70.0, "near_ready",    "Almost there — close the remaining gaps"),
    (50.0, "progressing",   "Good progress, keep building key skills"),
    (30.0, "early_stage",   "Good starting point, structured plan needed"),
    (0.0,  "just_starting", "Begin with fundamentals — long journey ahead"),
]

_STOP_WORDS: set = {
    "a","an","the","and","or","of","in","to","for",
    "with","on","at","by","from","is","are","was",
    "be","as","it","its","this","that","which","using",
    "used","use","via","based","related","including",
}

# ══════════════════════════════════════════════════════════════════════════════
#  CAREER AGENT
# ══════════════════════════════════════════════════════════════════════════════

class CareerAgent:
    """Career transition agent — DB first, LLM fallback, BM25 skill matching."""

    _llm = None
    _roadmap_skill_cache: Dict[str, List[Dict[str, Any]]] = {}

    def __init__(self, esco_repo=None, llm_client: Optional[Any] = None, **_: Any):
        self._bm25_match_threshold = BM25_MATCH_THRESHOLD
        self.esco_repo = esco_repo
        self.tools = CareerTools(esco_repo=esco_repo)
        if llm_client is not None:
            CareerAgent._llm = llm_client

    # ══════════════════════════════════════════════════════════════════════════
    #  DATABASE
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def get_db_connection():
        """Create and return a PostgreSQL connection."""
        database_url = os.getenv("DATABASE_URL") or settings.database_url
        return psycopg2.connect(database_url)

    @staticmethod
    def ensure_db_schema() -> None:
        """Create required tables/indexes if they do not already exist."""
        conn   = None
        cursor = None
        try:
            conn   = CareerAgent.get_db_connection()
            cursor = conn.cursor()

            # ── job_roles ──────────────────────────────────────────────────
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS job_roles (
                    id         SERIAL PRIMARY KEY,
                    title      TEXT NOT NULL UNIQUE,
                    summary    TEXT,
                    department TEXT
                )
            """)

            # ── job_role_skills ────────────────────────────────────────────
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS job_role_skills (
                    id             SERIAL PRIMARY KEY,
                    job_role_id    INTEGER NOT NULL REFERENCES job_roles(id) ON DELETE CASCADE,
                    skill_name     TEXT NOT NULL,
                    category       TEXT,
                    required_level TEXT NOT NULL,
                    importance     INTEGER DEFAULT 1,
                    depends_on     TEXT,
                    bm25_expansion TEXT,
                    UNIQUE (job_role_id, skill_name)
                )
            """)

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_job_roles_title "
                "ON job_roles (LOWER(title))"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_job_role_skills_role_id "
                "ON job_role_skills (job_role_id)"
            )

            conn.commit()
            print("[DB] Schema check complete.")

        except Exception as exc:
            if conn:
                conn.rollback()
            print(f"[DB] Schema initialization failed: {exc}")
        finally:
            if cursor: cursor.close()
            if conn:   conn.close()

    # ──────────────────────────────────────────────────────────────────────────
    #  FETCH FROM DB
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def fetch_job_role_from_db(job_role_title: str) -> dict | None:
        """
        Fetch job role + all skills from PostgreSQL.
        Returns structured dict or None if not found.
        """
        conn   = None
        cursor = None
        try:
            conn   = CareerAgent.get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # ── Fetch role ─────────────────────────────────────────────────
            cursor.execute(
                """
                SELECT id, title, summary, department
                FROM job_roles
                WHERE LOWER(title) = LOWER(%s)
                """,
                (job_role_title.strip(),),
            )
            job_role = cursor.fetchone()

            if not job_role:
                print(f"[DB] Role '{job_role_title}' not found.")
                return None

            job_role_dict = dict(job_role)
            job_role_id   = job_role_dict.pop("id")

            # ── Fetch skills ───────────────────────────────────────────────
            cursor.execute(
                """
                SELECT
                    skill_name,
                    category,
                    required_level,
                    importance,
                    depends_on,
                    bm25_expansion
                FROM job_role_skills
                WHERE job_role_id = %s
                ORDER BY importance DESC, skill_name
                """,
                (job_role_id,),
            )
            skills = [dict(row) for row in cursor.fetchall()]

            job_role_dict["skills"] = skills
            print(f"[DB] Role '{job_role_title}' found - {len(skills)} skills loaded.")
            return job_role_dict

        except psycopg2.Error as exc:
            print(f"[DB] Database error: {exc}")
            return None
        except Exception as exc:
            print(f"[DB] Unexpected error: {exc}")
            return None
        finally:
            if cursor: cursor.close()
            if conn:   conn.close()

    # ──────────────────────────────────────────────────────────────────────────
    #  SAVE TO DB
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def save_job_description(jd_data: dict) -> int:
        """
        Save normalized JD dict into job_roles + job_role_skills.
        Returns job_role_id.
        """
        conn = CareerAgent.get_db_connection()
        try:
            with conn:
                with conn.cursor() as cur:

                    # ── Check existing ─────────────────────────────────────
                    cur.execute(
                        "SELECT id FROM job_roles WHERE LOWER(title) = LOWER(%s)",
                        (str(jd_data.get("title", "")).strip(),),
                    )
                    existing = cur.fetchone()
                    if existing:
                        role_id = existing[0]
                        # If the role exists but has no skills yet, backfill skill rows.
                        cur.execute(
                            "SELECT COUNT(*) FROM job_role_skills WHERE job_role_id = %s",
                            (role_id,),
                        )
                        skill_count = int(cur.fetchone()[0] or 0)
                        if skill_count > 0:
                            print(f"[DB] Role already exists (id={role_id}), skipping insert.")
                            return role_id

                        for skill in jd_data.get("skills", []):
                            cur.execute(
                                """
                                INSERT INTO job_role_skills (
                                    job_role_id, skill_name, category,
                                    required_level, importance, depends_on, bm25_expansion
                                )
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (job_role_id, skill_name) DO NOTHING
                                """,
                                (
                                    role_id,
                                    str(skill.get("skill_name", "")).strip().lower(),
                                    str(skill.get("category", "General")).strip(),
                                    str(skill.get("required_level", "beginner")).strip(),
                                    int(skill.get("importance", 1)),
                                    skill.get("depends_on") or None,
                                    str(skill.get("bm25_expansion", "")).strip() or None,
                                ),
                            )
                        print(f"[DB] Backfilled {len(jd_data.get('skills', []))} skills for existing role (id={role_id}).")
                        return role_id

                    # ── Insert job_roles ───────────────────────────────────
                    cur.execute(
                        """
                        INSERT INTO job_roles (title, summary, department)
                        VALUES (%s, %s, %s)
                        RETURNING id
                        """,
                        (
                            str(jd_data.get("title", "")).strip(),
                            str(jd_data.get("summary", "")).strip(),
                            str(jd_data.get("department", "")).strip(),
                        ),
                    )
                    role_id = cur.fetchone()[0]
                    print(f"[DB] Job role inserted (id={role_id})")

                    # ── Insert job_role_skills ─────────────────────────────
                    for skill in jd_data.get("skills", []):
                        cur.execute(
                            """
                            INSERT INTO job_role_skills (
                                job_role_id, skill_name, category,
                                required_level, importance, depends_on, bm25_expansion
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (job_role_id, skill_name) DO NOTHING
                            """,
                            (
                                role_id,
                                str(skill.get("skill_name", "")).strip().lower(),
                                str(skill.get("category", "General")).strip(),
                                str(skill.get("required_level", "beginner")).strip(),
                                int(skill.get("importance", 1)),
                                skill.get("depends_on") or None,
                                str(skill.get("bm25_expansion", "")).strip() or None,
                            ),
                        )
                    print(f"[DB] {len(jd_data.get('skills', []))} skills inserted.")

            return role_id

        finally:
            conn.close()

    # ══════════════════════════════════════════════════════════════════════════
    #  LLM
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _get_llm():
        if CareerAgent._llm is None:
            model   = os.getenv("GROQ_LLM_MODEL") or "llama-3.3-70b-versatile"
            api_key = os.getenv("GROQ_API_KEY") or settings.groq_api_key
            if not api_key:
                raise ValueError("GROQ_API_KEY not set.")
            CareerAgent._llm = ChatGroq(api_key=api_key, model=model, temperature=0)
        return CareerAgent._llm

    @staticmethod
    def get_job_description_prompt(job_role: str) -> str:
        return f"""
You are an expert Technical Recruitment Architect with 20+ years of experience
designing structured job descriptions for automated skill-matching systems.

Your task: Generate a COMPLETE and DETAILED job description for the role: "{job_role}"

═══════════════════════════════════════════════════════════════
⚠️  STRICT RULES — FOLLOW ALL:
═══════════════════════════════════════════════════════════════

1.  Return ONLY a valid JSON object. No markdown, no explanation, no backticks.
2.  The JSON MUST exactly follow the schema below — no missing fields.
3.  All required_level values MUST be one of: "beginner", "intermediate", "advanced"
4.  importance MUST be an integer from 1 (lowest) to 5 (highest)
5.  Include ALL technical skills relevant to the role — aim for 15 to 25 skills minimum
6.  DO NOT include soft skills (no communication, teamwork, leadership, etc.)
7.  Only include hard technical skills, tools, frameworks, languages, and platforms
8.  Every skill MUST include a bm25_expansion field:
    - Space-separated string of synonyms, abbreviations, aliases, related tools
    - Candidates use these terms on resumes
    - Include 8 to 15 tokens per skill
    - Example for "react": "reactjs react.js react-dom jsx hooks redux context-api spa frontend"
9.  depends_on: name of another skill this skill requires as prerequisite, or null
10. The response must be parseable by Python json.loads() directly
11. category must group skills logically (e.g. "Frontend Frameworks", "Databases", "DevOps")
12. Cover ALL major competency areas for the role — be thorough and comprehensive

═══════════════════════════════════════════════════════════════
📋 EXACT JSON SCHEMA:
═══════════════════════════════════════════════════════════════

{{
  "title"     : "{job_role}",
  "summary"   : "<2-3 sentence role summary>",
  "department": "<Department Name>",
  "skills": [
    {{
      "skill_name"    : "<skill name in lowercase>",
      "category"      : "<Category Name>",
      "required_level": "<beginner | intermediate | advanced>",
      "importance"    : <1-5 integer>,
      "depends_on"    : "<prerequisite skill name or null>",
      "bm25_expansion": "<space separated synonym tokens>"
    }}
  ]
}}

═══════════════════════════════════════════════════════════════
🎯 QUALITY REQUIREMENTS:
═══════════════════════════════════════════════════════════════

- Generate realistic, industry-standard skills for "{job_role}"
- Skills must reflect current market demands (2024-2025)
- High importance (4-5) = core non-negotiable skills
- Medium importance (3) = valuable but not mandatory
- Low importance (1-2) = nice-to-have differentiators
- bm25_expansion must include all common resume aliases for that skill
- Be exhaustive — missing skills means poor matching for candidates

Now generate the complete JSON for: "{job_role}"
"""

    @staticmethod
    def fetch_job_role_from_llm(job_role_title: str) -> dict | None:
        """Use Groq LLM to generate job description. Returns normalized dict or None."""
        try:
            print(f"[LLM] Generating job description for '{job_role_title}'...")
            client   = CareerAgent._get_llm()
            prompt   = CareerAgent.get_job_description_prompt(job_role_title)
            messages = [
                SystemMessage(content=(
                    "You are a structured data generator. "
                    "Output ONLY valid JSON parseable by json.loads(). "
                    "No markdown, no explanation, no code blocks."
                )),
                HumanMessage(content=prompt),
            ]
            response    = client.invoke(messages)
            raw_response = response.content.strip()
            print("[LLM] Response received.")

            parsed = CareerAgent._parse_llm_json(raw_response)
            if parsed:
                print(f"[LLM] JSON parsed - {len(parsed.get('skills', []))} skills found.")
                return parsed
            else:
                print("[LLM] Failed to parse JSON.")
                return None

        except Exception as exc:
            print(f"[LLM] Error: {exc}")
            return None

    @staticmethod
    def _parse_llm_json(raw_text: str) -> dict | None:
        """Safely parse JSON from LLM response with multiple fallback strategies."""
        # Attempt 1: Direct parse
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            pass

        # Attempt 2: Strip markdown fences
        try:
            cleaned = re.sub(r"```(?:json)?", "", raw_text).strip().strip("`").strip()
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Attempt 3: Extract JSON object via regex
        try:
            match = re.search(r"\{.*\}", raw_text, re.DOTALL)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass

        return None

    # ══════════════════════════════════════════════════════════════════════════
    #  GET JOB DESCRIPTION  (DB → LLM → Cache)
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def get_job_description(role: str) -> dict:
        """DB first, LLM fallback. Caches LLM result back to DB."""

        # ── Try DB ─────────────────────────────────────────────────────────
        db_data = CareerAgent.fetch_job_role_from_db(role)
        if db_data and db_data.get("skills"):
            return {"source": "database", "job_description": db_data}
        if db_data and not db_data.get("skills"):
            print(f"[DB] Role '{role}' has no skills; falling back to LLM/backfill.")

        # ── Try LLM ────────────────────────────────────────────────────────
        llm_data = CareerAgent.fetch_job_role_from_llm(role)
        if llm_data:
            try:
                role_id = CareerAgent.save_job_description(llm_data)
                print(f"[DB] Cached LLM result for '{role}' (id={role_id})")
            except Exception as exc:
                print(f"[DB] Failed to cache LLM result: {exc}")
            return {"source": "llm", "job_description": llm_data}

        return {"source": "none", "job_description": None}

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 1 — INITIALIZE USER SKILL LEVELS (RANDOM)
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def initialize_user_skill_levels(user_skills: list[str]) -> list[dict]:
        """
        Take a flat list of skill name strings and assign a random proficiency
        level to each one.

        Returns a list of dicts:
        [
            {
                "skill_name"    : "react",
                "inferred_level": "intermediate",
                "level_int"     : 2,
            },
            ...
        ]
        """
        initialized = []
        for skill in user_skills:
            skill_clean = str(skill).strip().lower()
            if not skill_clean:
                continue

            level_str = random.choice(LEVEL_POOL)
            level_int = LEVEL_STR_TO_INT[level_str]

            initialized.append({
                "skill_name"    : skill_clean,
                "inferred_level": level_str,
                "level_int"     : level_int,
            })

            logger.debug(f"[LevelInit] {skill_clean:<25} → {level_str} (lvl {level_int})")

        logger.info(f"[LevelInit] ✅ {len(initialized)} user skills initialized with random levels.")
        return initialized

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 2 — TOKENIZER
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenize text for BM25. Keeps compound tokens like c++, .net, ci/cd."""
        if not text:
            return []
        text   = text.lower()
        tokens = re.findall(r"[a-z0-9][a-z0-9\+\#\.\/\-\_]*", text)
        return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 3 — BM25 INDEX + MATCHING
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _build_role_skill_document(role_skill: dict) -> list[str]:
        """
        Build BM25 corpus document for ONE role skill.
        Combines bm25_expansion (boosted) + skill_name.
        """
        parts: list[str] = []

        expansion = str(role_skill.get("bm25_expansion") or "").strip()
        if expansion:
            # Repeat expansion twice to boost its BM25 weight
            parts.append(expansion)
            parts.append(expansion)

        parts.append(str(role_skill.get("skill_name") or ""))

        return CareerAgent._tokenize(" ".join(parts))

    @staticmethod
    def _build_user_skill_query(user_skill: dict) -> list[str]:
        """Build BM25 query tokens for ONE user skill."""
        return CareerAgent._tokenize(str(user_skill.get("skill_name") or ""))

    @staticmethod
    def _build_bm25_index(role_skills: list[dict]) -> tuple:
        """Build BM25Okapi index — one document per role skill."""
        corpus = [CareerAgent._build_role_skill_document(rs) for rs in role_skills]
        bm25   = BM25Okapi(corpus)
        logger.info(f"[BM25] ✅ Index built — {len(corpus)} role skill documents.")
        return bm25, corpus

    @staticmethod
    def _find_best_match_for_role_skill(
        role_skill_idx: int,
        user_skills   : list[dict],
        bm25          : BM25Okapi,
        threshold     : float,
    ) -> tuple:
        """
        For ONE role skill, find the best matching user skill using BM25.
        Returns (best_user_skill_dict, best_score) or (None, 0.0).
        """
        best_score = 0.0
        best_skill = None

        for u_skill in user_skills:
            query = CareerAgent._build_user_skill_query(u_skill)
            if not query:
                continue
            scores     = bm25.get_scores(query)
            this_score = float(scores[role_skill_idx])
            if this_score > best_score:
                best_score = this_score
                best_skill = u_skill

        if best_score < threshold:
            return None, 0.0

        return best_skill, round(best_score, 4)

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 4 — LEVEL COMPARISON + CLASSIFICATION
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _required_level_to_int(level_str: str) -> int:
        return LEVEL_STR_TO_INT.get(str(level_str).lower().strip(), 1)

    @staticmethod
    def _compute_priority(gap: int, importance: int) -> str:
        """
        Derive priority from gap size and importance score (1-5).
        importance 4-5 = core skills → higher priority
        """
        if importance >= 4:
            return "critical" if gap >= 2 else "high"
        if importance == 3:
            return "medium" if gap >= 2 else "low"
        return "low"

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 5 — READINESS SCORE
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _compute_readiness_score(
        role_skills  : list[dict],
        match_results: dict,
    ) -> float:
        """
        Weighted readiness score (0–100).

        Per skill:
            contribution = (user_level / required_level) × importance_weight
            max          = 1.0 × importance_weight

        importance_weight = importance (1-5) from DB
        """
        total_max    = 0.0
        total_earned = 0.0

        for rs in role_skills:
            skill_name   = rs["skill_name"].lower()
            importance   = int(rs.get("importance", 1))
            required_lvl = CareerAgent._required_level_to_int(rs.get("required_level", "beginner"))

            total_max += float(importance)

            match = match_results.get(skill_name)
            if match and match["user_level_int"] > 0:
                ratio        = min(match["user_level_int"] / required_lvl, 1.0) if required_lvl else 0.0
                total_earned += ratio * float(importance)

        if total_max == 0:
            return 0.0

        return round((total_earned / total_max) * 100, 2)

    @staticmethod
    def _get_readiness_category(score: float) -> tuple:
        for threshold, category, message in READINESS_CATEGORIES:
            if score >= threshold:
                return category, message
        return "just_starting", "Begin with fundamentals — long journey ahead"

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 6 — DEPENDENCY ANALYSIS
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _analyze_dependencies(
        role_skills  : list[dict],
        match_results: dict,
    ) -> dict:
        """
        For each skill that has a depends_on, check if the dependency is met.
        Returns dependency analysis dict.
        """
        output: dict = {}

        for rs in role_skills:
            skill_name = rs["skill_name"].lower()
            depends_on = rs.get("depends_on")

            if not depends_on:
                continue

            dep_skill = str(depends_on).strip().lower()
            dep_match = match_results.get(dep_skill)
            dep_required = CareerAgent._required_level_to_int(
                next(
                    (r["required_level"] for r in role_skills if r["skill_name"].lower() == dep_skill),
                    "beginner"
                )
            )

            dep_met = (
                dep_match is not None
                and dep_match["user_level_int"] >= dep_required
            )

            output[skill_name] = {
                "requires"       : dep_skill,
                "dependency_met" : dep_met,
                "missing_dep"    : dep_skill if not dep_met else None,
            }

        return output

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 7 — RECOMMENDATIONS
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _generate_recommendations(
        skill_gaps      : list[dict],
        missing_skills  : list[dict],
        dep_analysis    : dict,
        target_role     : str,
    ) -> dict:
        """Rule-based recommendation engine."""
        immediate  : list[str] = []
        short_term : list[str] = []
        long_term  : list[str] = []

        # ── Immediate: close gaps ──────────────────────────────────────────
        for gap in skill_gaps:
            skill    = gap["skill_name"]
            user_lvl = gap["user_level_str"]
            req_lvl  = gap["required_level_str"]
            is_blocker = any(
                info.get("requires") == skill and not info.get("dependency_met")
                for info in dep_analysis.values()
            )
            if is_blocker:
                immediate.append(
                    f"Urgently strengthen '{skill}' from {user_lvl} → {req_lvl} "
                    f"(it is a prerequisite for other required skills)"
                )
            else:
                immediate.append(
                    f"Close the '{skill}' gap: currently {user_lvl}, need {req_lvl}"
                )

        # ── Immediate: missing high-importance skills with no unmet deps ───
        for ms in missing_skills:
            skill    = ms["skill_name"]
            dep_info = dep_analysis.get(skill, {})
            if dep_info.get("dependency_met", True) and ms["importance"] >= 4:
                immediate.append(
                    f"Start learning '{skill}' immediately — core requirement, no prerequisites"
                )

        # ── Short-term: build missing skills ──────────────────────────────
        for ms in missing_skills:
            skill    = ms["skill_name"]
            dep_info = dep_analysis.get(skill, {})
            missing_dep = dep_info.get("missing_dep")
            if missing_dep:
                short_term.append(
                    f"Learn '{skill}' after completing '{missing_dep}' first"
                )
            else:
                short_term.append(
                    f"Build hands-on projects using '{skill}' to reach "
                    f"required level: {ms['required_level_str']}"
                )

        for gap in skill_gaps:
            short_term.append(
                f"Practice '{gap['skill_name']}' through targeted exercises "
                f"to reach {gap['required_level_str']}"
            )

        # ── Long-term ──────────────────────────────────────────────────────
        all_gap_skills = [g["skill_name"] for g in skill_gaps + missing_skills]
        if all_gap_skills:
            long_term.append(
                f"Build a full {target_role} project combining: "
                f"{', '.join(all_gap_skills[:6])}"
            )
        long_term.append(
            f"Contribute to a production-grade {target_role} codebase "
            f"using all required skills"
        )

        return {
            "immediate_actions": immediate,
            "short_term_goals" : short_term,
            "long_term_goals"  : long_term,
        }

    # ══════════════════════════════════════════════════════════════════════════
    #  MAIN ANALYZER
    # ══════════════════════════════════════════════════════════════════════════

    def analyze_skill_gap(
        self,
        user_profile : dict,
        target_role  : str,
    ) -> dict:
        """
        Full pipeline:
        1. Initialize random levels for user skills
        2. Fetch role from DB → LLM fallback → cache to DB
        3. BM25 match user skills → role skills
        4. Compare levels → classify into matched / skill_gaps / unmatched
        5. Compute readiness score
        6. Dependency analysis
        7. Recommendations
        8. Return full report

        Parameters
        ----------
        user_profile : dict with keys:
                        name, employee_id, current_role,
                        experience_years, skills (list of str)
        target_role  : str — e.g. "Full Stack Developer"

        Returns
        -------
        dict — complete report
        """

        # ── Unpack user profile ────────────────────────────────────────────
        raw_skills     = user_profile.get("skills", [])
        employee_id    = str(user_profile.get("employee_id", ""))
        name           = str(user_profile.get("name", "Employee"))
        current_role   = str(user_profile.get("current_role", user_profile.get("role", "")))
        exp_years      = float(user_profile.get("experience_years", user_profile.get("experience", 0)))

        logger.info(f"[Analyzer] ▶ '{name}' | {current_role} → {target_role} | {len(raw_skills)} skills")

        # ══════════════════════════════════════════════════════════════════
        #  STEP 1 — Initialize random levels for user skills
        # ══════════════════════════════════════════════════════════════════

        user_skills_with_levels = CareerAgent.initialize_user_skill_levels(raw_skills)

        # ══════════════════════════════════════════════════════════════════
        #  STEP 2 — Fetch role data (DB → LLM → Cache)
        # ══════════════════════════════════════════════════════════════════

        jd_result       = CareerAgent.get_job_description(target_role)
        source          = jd_result.get("source", "none")
        job_description = jd_result.get("job_description")

        if not isinstance(job_description, dict):
            logger.error(f"[Analyzer] ❌ Could not fetch role data for '{target_role}'")
            return {"error": f"Could not fetch job description for '{target_role}'"}

        role_skills: list[dict] = job_description.get("skills", [])

        if not role_skills:
            logger.error(f"[Analyzer] ❌ No skills found for role '{target_role}'")
            return {"error": f"No skills found for role '{target_role}'"}

        logger.info(f"[Analyzer] ✅ Role '{target_role}' loaded from {source} — {len(role_skills)} skills")

        # ══════════════════════════════════════════════════════════════════
        #  STEP 3 — Build BM25 index on role skills
        # ══════════════════════════════════════════════════════════════════

        bm25, _ = CareerAgent._build_bm25_index(role_skills)

        # ══════════════════════════════════════════════════════════════════
        #  STEP 4 — Match each role skill against user skills via BM25
        #           Then compare levels → classify
        # ══════════════════════════════════════════════════════════════════

        matched_skills : list[dict] = []
        skill_gaps     : list[dict] = []
        unmatched      : list[dict] = []

        # match_results: role_skill_name → detail (used for readiness + deps)
        match_results: dict[str, dict] = {}

        for idx, rs in enumerate(role_skills):
            role_skill_name  = str(rs["skill_name"]).strip().lower()
            required_lvl_str = str(rs.get("required_level", "beginner")).strip().lower()
            required_lvl_int = CareerAgent._required_level_to_int(required_lvl_str)
            importance       = int(rs.get("importance", 1))
            category         = str(rs.get("category", "")).strip()
            depends_on       = rs.get("depends_on")
            bm25_expansion   = str(rs.get("bm25_expansion") or "").strip()

            # ── BM25: find best matching user skill ───────────────────────
            best_user_skill, bm25_score = CareerAgent._find_best_match_for_role_skill(
                role_skill_idx = idx,
                user_skills    = user_skills_with_levels,
                bm25           = bm25,
                threshold      = self._bm25_match_threshold,
            )

            # ── Build base skill record (all DB attributes) ───────────────
            skill_record = {
                # ── DB attributes ─────────────────────────────────────────
                "skill_name"        : role_skill_name,
                "category"          : category,
                "required_level_str": required_lvl_str,
                "required_level_int": required_lvl_int,
                "importance"        : importance,
                "depends_on"        : depends_on,
                "bm25_expansion"    : bm25_expansion,
                # ── Match info ────────────────────────────────────────────
                "bm25_score"        : bm25_score,
                "matched_user_skill": best_user_skill.get("skill_name") if best_user_skill else None,
            }

            if best_user_skill:
                user_lvl_int = best_user_skill["level_int"]
                user_lvl_str = best_user_skill["inferred_level"]
            else:
                user_lvl_int = 0
                user_lvl_str = "none"

            skill_record["user_level_int"] = user_lvl_int
            skill_record["user_level_str"] = user_lvl_str

            # ── Store in match_results for readiness + dep analysis ───────
            match_results[role_skill_name] = skill_record

            # ══════════════════════════════════════════════════════════════
            #  CLASSIFICATION
            #
            #  Case 1 — No BM25 match found → UNMATCHED (skill missing)
            #  Case 2 — Match found, user_level >= required → MATCHED ✅
            #  Case 3 — Match found, user_level < required  → SKILL GAP ⚠️
            # ══════════════════════════════════════════════════════════════

            if not best_user_skill:
                # ── UNMATCHED ──────────────────────────────────────────────
                priority = CareerAgent._compute_priority(required_lvl_int, importance)
                unmatched.append({
                    **skill_record,
                    "gap"     : required_lvl_int,
                    "priority": priority,
                    "status"  : "missing",
                })
                logger.debug(f"[Match] ❌ MISSING   {role_skill_name:<25} req={required_lvl_str}")

            elif user_lvl_int >= required_lvl_int:
                # ── MATCHED ───────────────────────────────────────────────
                matched_skills.append({
                    **skill_record,
                    "gap"     : 0,
                    "priority": "none",
                    "status"  : "matched",
                })
                logger.debug(
                    f"[Match] ✅ MATCHED   {role_skill_name:<25} "
                    f"user={user_lvl_str} req={required_lvl_str} BM25={bm25_score}"
                )

            else:
                # ── SKILL GAP ─────────────────────────────────────────────
                gap      = required_lvl_int - user_lvl_int
                priority = CareerAgent._compute_priority(gap, importance)
                skill_gaps.append({
                    **skill_record,
                    "gap"     : gap,
                    "priority": priority,
                    "status"  : "gap",
                })
                logger.debug(
                    f"[Match] ⚠️  GAP      {role_skill_name:<25} "
                    f"user={user_lvl_str} req={required_lvl_str} gap={gap} BM25={bm25_score}"
                )

        # ── Sort by priority ───────────────────────────────────────────────
        def _sort_key(item):
            return (PRIORITY_ORDER.get(item.get("priority", "low"), 99), -item.get("gap", 0))

        skill_gaps.sort(key=_sort_key)
        unmatched.sort(key=_sort_key)

        # ══════════════════════════════════════════════════════════════════
        #  STEP 5 — Readiness Score
        # ══════════════════════════════════════════════════════════════════

        readiness_score    = CareerAgent._compute_readiness_score(role_skills, match_results)
        readiness_category, readiness_message = CareerAgent._get_readiness_category(readiness_score)

        # ══════════════════════════════════════════════════════════════════
        #  STEP 6 — Dependency Analysis
        # ══════════════════════════════════════════════════════════════════

        dep_analysis = CareerAgent._analyze_dependencies(role_skills, match_results)

        # ══════════════════════════════════════════════════════════════════
        #  STEP 7 — Recommendations
        # ══════════════════════════════════════════════════════════════════

        recommendations = CareerAgent._generate_recommendations(
            skill_gaps    = skill_gaps,
            missing_skills= unmatched,
            dep_analysis  = dep_analysis,
            target_role   = target_role,
        )

        # ══════════════════════════════════════════════════════════════════
        #  STEP 8 — Assemble Final Report
        # ══════════════════════════════════════════════════════════════════

        report = {

            # ── User profile ───────────────────────────────────────────────

            # ── User skills with initialized levels ────────────────────────

            # ── Job description metadata ───────────────────────────────────
            "job_description_meta": {
                "title"     : job_description.get("title", target_role),
                "summary"   : job_description.get("summary", ""),
                "department": job_description.get("department", ""),
                "total_required_skills": len(role_skills),
            },

            # ── Readiness summary ──────────────────────────────────────────
            "readiness_summary": {
                "readiness_score"      : readiness_score,
                "readiness_category"   : readiness_category,
                "total_skills_required": len(role_skills),
                "skills_matched"       : len(matched_skills),
                "skills_with_gaps"     : len(skill_gaps),
                "skills_missing"       : len(unmatched),
            },

            # ── Full skill analysis with ALL DB attributes per skill ────────
            "skill_analysis": {
                "matched_skills": matched_skills,
                "skill_gaps"    : skill_gaps,
                "unmatched_skills": unmatched,
            },

            # ── Dependency analysis ────────────────────────────────────────
            "skill_dependencies": dep_analysis,

            # ── Recommendations ────────────────────────────────────────────
            "recommendations": recommendations,
        }

        logger.info(
            f"[Analyzer] ✅ Report ready | "
            f"Score: {readiness_score}% ({readiness_category}) | "
            f"Matched: {len(matched_skills)} | "
            f"Gaps: {len(skill_gaps)} | "
            f"Missing: {len(unmatched)}"
        )

        return report

    def _normalize_skill_label(self, value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().lower())

    def _role_slug_candidates(self, role: str) -> List[str]:
        value = self._normalize_skill_label(role)
        if not value:
            return []
        slug = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
        compact = re.sub(r"[^a-z0-9]", "", value)
        parts = [part for part in re.split(r"[^a-z0-9]+", value) if part]

        candidates = [slug]
        if parts:
            candidates.append("_".join(parts))
        if compact:
            candidates.append(compact)
        if slug.endswith("developer"):
            candidates.append(slug.replace("developer", "dev"))
        if slug.endswith("engineer"):
            candidates.append(slug.replace("engineer", "eng"))
        return list(dict.fromkeys(candidate for candidate in candidates if candidate))

    def _load_roadmap_required_skills(self, target_role: str) -> List[Dict[str, Any]]:
        role_key = self._normalize_skill_label(target_role)
        if role_key in self._roadmap_skill_cache:
            return self._roadmap_skill_cache[role_key]

        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "roadmap_agent"))
        folders = [
            os.path.join(base_dir, "roadmaps_standard"),
            os.path.join(base_dir, "topics_only"),
        ]

        roadmap_file = ""
        for folder in folders:
            if not os.path.isdir(folder):
                continue
            for candidate in self._role_slug_candidates(target_role):
                candidate_path = os.path.join(folder, f"{candidate}.json")
                if os.path.isfile(candidate_path):
                    roadmap_file = candidate_path
                    break
            if roadmap_file:
                break

        if not roadmap_file:
            self._roadmap_skill_cache[role_key] = []
            return []

        try:
            with open(roadmap_file, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as error:
            logger.warning("Failed to load roadmap file '%s': %s", roadmap_file, error)
            self._roadmap_skill_cache[role_key] = []
            return []

        skills: List[Dict[str, Any]] = []
        for phase in data.get("phases", []) or []:
            phase_title = str(phase.get("phase_title", "")).strip()
            for node in phase.get("nodes", []) or []:
                if not isinstance(node, dict):
                    continue
                label = str(node.get("label", "")).strip()
                if not label:
                    continue

                node_type = str(node.get("type", "")).strip().lower()
                if node_type not in {"topic", "subtopic"}:
                    continue

                normalized = self._normalize_skill_label(label)
                if not normalized:
                    continue

                skills.append(
                    {
                        "skill_name": label,
                        "normalized": normalized,
                        "category": str(node.get("category", phase_title or "roadmap")).strip() or "roadmap",
                        "importance": str(node.get("importance", "important")).strip().lower(),
                        "source": "roadmap",
                    }
                )

        dedup: Dict[str, Dict[str, Any]] = {}
        for item in skills:
            key = item.get("normalized", "")
            if key and key not in dedup:
                dedup[key] = item

        result = list(dedup.values())
        self._roadmap_skill_cache[role_key] = result
        logger.info("Loaded %s roadmap skills for role '%s' from %s", len(result), target_role, os.path.basename(roadmap_file))
        return result

    def _compute_direct_skill_gap_context(self, target_role: str, current_skills: List[str]) -> Dict[str, Any]:
        """Build deterministic skill-gap context from target-role required skills and current skills."""
        jd_result = CareerAgent.get_job_description(target_role)
        job_description = jd_result.get("job_description") if isinstance(jd_result, dict) else {}
        role_skills = job_description.get("skills", []) if isinstance(job_description, dict) else []

        required_map: Dict[str, Dict[str, Any]] = {}
        for item in role_skills:
            if not isinstance(item, dict):
                continue
            raw = str(item.get("skill_name", "")).strip()
            if raw:
                normalized = self._normalize_skill_label(raw)
                if normalized and normalized not in required_map:
                    required_map[normalized] = {
                        "skill_name": raw,
                        "normalized": normalized,
                        "category": str(item.get("category", "core")).strip() or "core",
                        "importance": "core" if int(item.get("importance", 1) or 1) >= 4 else "important",
                        "source": "role_profile",
                    }

        # Resilient fallback: if DB/LLM role profile is unavailable, try ESCO.
        if not required_map and self.esco_repo and hasattr(self.esco_repo, "get_skills_for_occupation"):
            try:
                esco_skills = self.esco_repo.get_skills_for_occupation(target_role) or []
                for skill in esco_skills:
                    raw = str(skill or "").strip()
                    normalized = self._normalize_skill_label(raw)
                    if normalized and normalized not in required_map:
                        required_map[normalized] = {
                            "skill_name": raw,
                            "normalized": normalized,
                            "category": "esco",
                            "importance": "important",
                            "source": "esco_live",
                        }
                if esco_skills:
                    logger.info(
                        "Using ESCO fallback skills for role '%s' (count=%s)",
                        target_role,
                        len(esco_skills),
                    )
            except Exception as error:
                logger.warning("ESCO fallback skill load failed for role '%s': %s", target_role, error)

        # roadmap_skills = self._load_roadmap_required_skills(target_role)
        # for item in roadmap_skills:
        #     normalized = item.get("normalized", "")
        #     if normalized and normalized not in required_map:
        #         required_map[normalized] = item

        required_entries = list(required_map.values())
        required_entries.sort(
            key=lambda value: (
                0 if value.get("importance") == "core" else 1 if value.get("importance") == "important" else 2,
                str(value.get("skill_name", "")).lower(),
            )
        )
        required_skills: List[str] = [str(item.get("skill_name", "")).strip() for item in required_entries if str(item.get("skill_name", "")).strip()]

        normalized_current = [self._normalize_skill_label(skill) for skill in current_skills if self._normalize_skill_label(skill)]

        matched: List[str] = []
        partial: List[Dict[str, Any]] = []
        missing_core: List[Dict[str, Any]] = []

        for entry in required_entries:
            required_label = str(entry.get("skill_name", "")).strip()
            required_norm = str(entry.get("normalized", "")).strip()
            req_tokens = set(CareerAgent._tokenize(required_norm))
            best_overlap = 0
            exact_or_alias = False

            for current in normalized_current:
                if current == required_norm:
                    exact_or_alias = True
                    break
                if len(required_norm) >= 3 and (required_norm in current or current in required_norm):
                    exact_or_alias = True
                    break

                cur_tokens = set(CareerAgent._tokenize(current))
                overlap = len(req_tokens & cur_tokens)
                if overlap > best_overlap:
                    best_overlap = overlap

            if exact_or_alias:
                matched.append(required_label)
            elif best_overlap > 0:
                partial.append({
                    "skill": required_label,
                    "gap": 1,
                    "priority": "high",
                    "category": entry.get("category", "general"),
                })
            else:
                missing_core.append({
                    "skill": required_label,
                    "gap": 1,
                    "priority": "critical",
                    "category": entry.get("category", "general"),
                })

        total_required = len(required_skills)
        weighted_progress = len(matched) + (0.5 * len(partial))
        readiness_score = round((weighted_progress / total_required * 100.0) if total_required else 0.0, 2)
        readiness_category, readiness_message = CareerAgent._get_readiness_category(readiness_score)

        return {
            "source_agent": "career_agent",
            "source": jd_result.get("source", "unknown") if isinstance(jd_result, dict) else "unknown",
            "required_skills": required_skills,
            "current_skills": normalized_current,
            "readiness_summary": {
                "readiness_score": readiness_score,
                "readiness_category": readiness_category,
                "readiness_message": readiness_message,
                "total_skills_required": total_required,
                "skills_completed": len(matched),
                "skills_partial": len(partial),
                "skills_missing": len(missing_core),
            },
            "core_gaps": [item["skill"] for item in (partial + missing_core)],
            "skill_analysis": {
                "matched_skills": matched,
                "skill_gaps": partial,
                "missing_core_skills": missing_core,
                "missing_optional_skills": [],
            },
        }

    # ══════════════════════════════════════════════════════════════════════════
    #  PUBLIC ENTRY POINT
    # ══════════════════════════════════════════════════════════════════════════

    def analyze_transition(
        self,
        skill_gap_context_or_profile: Any = None,
        target_role: Optional[str] = None,
        current_skills: Optional[List[str]] = None,
        user_profile: Optional[Dict[str, Any]] = None,
        **_: Any,
    ) -> dict:
        """Public API entry point compatible with both legacy and new call patterns."""
        profile: Dict[str, Any] = dict(user_profile or {})
        context_candidate = skill_gap_context_or_profile if isinstance(skill_gap_context_or_profile, dict) else {}

        # Legacy positional profile support: analyze_transition(profile, target_role)
        if not profile and context_candidate and any(
            key in context_candidate for key in ["skills", "name", "employee_id", "role", "current_role"]
        ):
            profile = dict(context_candidate)

        incoming_skill_gap_context: Dict[str, Any] = {}
        if context_candidate and any(
            key in context_candidate for key in ["readiness_summary", "skill_analysis", "core_gaps"]
        ):
            incoming_skill_gap_context = context_candidate

        resolved_current_role = str(
            profile.get("current_role")
            or profile.get("role")
            or (skill_gap_context_or_profile if isinstance(skill_gap_context_or_profile, str) else "")
            or "Unknown"
        )
        resolved_target_role = str(target_role or profile.get("target_role") or "Unknown Role")
        resolved_skills = [str(skill).strip() for skill in (current_skills or profile.get("skills", [])) if str(skill).strip()]

        # Build career-agent context first, then merge caller-provided gap context when available.
        skill_gap_context = self._compute_direct_skill_gap_context(
            target_role=resolved_target_role,
            current_skills=resolved_skills,
        )
        if incoming_skill_gap_context:
            for key in ["readiness_summary", "core_gaps", "skill_analysis"]:
                if key in incoming_skill_gap_context:
                    skill_gap_context[key] = incoming_skill_gap_context.get(key)

        feasibility = self.tools.analyze_transition_feasibility(
            current_role=resolved_current_role,
            target_role=resolved_target_role,
            current_skills=resolved_skills,
            skill_gap_context=skill_gap_context,
        )
        career_paths = self.tools.identify_career_path_options(resolved_current_role, resolved_skills)
        experience_years = int(profile.get("experience_years", profile.get("experience", 0)) or 0)
        timeline = self.tools.estimate_transition_timeline(
            skill_gaps=feasibility.get("critical_gaps", []),
            current_experience=experience_years,
        )

        score = float(feasibility.get("transition_score", 0.0) or 0.0)
        recommendation = {
            "recommendation": (
                "Proceed with transition now"
                if score >= 70
                else "Transition is feasible with a focused upskilling plan"
                if score >= 40
                else "Build foundations first before attempting full transition"
            ),
            "priority": "high" if score < 70 else "medium",
            "alternatives": career_paths.get("possible_transitions", [])[:3],
        }

        payload = {
            "input_profile": {
                "current_role": resolved_current_role,
                "target_role": resolved_target_role,
                "experience_years": experience_years,
            },
            "skill_gap_context": {
                "source_agent": str(skill_gap_context.get("source_agent", "skill_agent")),
                "current_skills": resolved_skills,
                "readiness_summary": skill_gap_context.get("readiness_summary", {}),
                "core_gaps": skill_gap_context.get("core_gaps", []),
                "skill_analysis": skill_gap_context.get("skill_analysis", {}),
            },
            "feasibility_analysis": feasibility,
            "career_path_options": career_paths,
            "transition_timeline": timeline,
            "recommendation": recommendation,
            "thought_process": [
                f"Analyzed transition from {resolved_current_role} to {resolved_target_role}",
                f"Evaluated {len(resolved_skills)} current skills",
                f"Computed transition score: {score}%",
                (
                    "Used provided skill-gap context as auxiliary input"
                    if incoming_skill_gap_context
                    else "Derived skill-gap context directly from target role requirements"
                ),
            ],
        }
        validated = CareerAgentOutputSchema.model_validate(payload).model_dump()
        return validated

# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    raw_payload = ""
    if not sys.stdin.isatty():
        raw_payload = sys.stdin.read().strip()

    if raw_payload:
        payload = json.loads(raw_payload)
    else:
        payload = {
            "profile": {
                "name"          : "Alex Johnson",
                "employee_id"   : "EMP-001",
                "role"          : "UI Developer",
                "experience"    : 4,
                "skills": [
                    "html", "css", "javascript", "typescript",
                    "react", "next.js", "redux", "tailwind",
                    "bootstrap", "material ui", "figma",
                    "jest", "unit testing", "responsive",
                    "lazy loading", "performance", "rest apis",
                    "authentication", "git", "github",
                ],
            },
            "target_role": "Full Stack Developer",
        }

    profile     = payload.get("profile", {})
    target_role = (
        payload.get("target_role")
        or profile.get("target_role")
        or "Full Stack Developer"
    )

    # Ensure schema exists
    CareerAgent.ensure_db_schema()

    agent  = CareerAgent()
    output = agent.analyze_transition(
        profile,
        user_profile=profile,
        target_role =target_role,
    )

    print(json.dumps(output, indent=2))



