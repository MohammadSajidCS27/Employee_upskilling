import logging
import uuid
import json
from typing import Any
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session
from src.models.models import Base, Employee, Skill, EmployeeSkill, Analysis, Roadmap, JobDescription, TalentMatch, User
from src.utils.password import hash_password, verify_password
from datetime import datetime, UTC

logger = logging.getLogger(__name__)

class PostgreSQLService:
    def __init__(self, database_url: str):
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.session_factory = scoped_session(sessionmaker(bind=self.engine))

    def init_db(self):
        Base.metadata.create_all(self.engine)
        session = self.session_factory()
        try:
            self._ensure_roadmap_tracking_tables(session)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        logger.info("Database initialized")

    def _ensure_roadmap_tracking_tables(self, session) -> None:
        session.execute(
            text(
                "ALTER TABLE employees ADD COLUMN IF NOT EXISTS current_roadmap_slug TEXT"
            )
        )
        session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS roadmap_nodes (
                  id SERIAL PRIMARY KEY,
                  node_key TEXT UNIQUE,
                  roadmap_slug TEXT NOT NULL DEFAULT 'generated',
                  roadmap_title TEXT,
                  node_id TEXT NOT NULL,
                  source_node_id TEXT,
                  title TEXT,
                  role TEXT,
                  node_type TEXT,
                  phase_id TEXT,
                  phase_title TEXT,
                  category TEXT,
                  raw_node JSONB,
                  source_file TEXT,
                  created_at TIMESTAMPTZ DEFAULT NOW(),
                  updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS roadmap_nodes_node_key_ux ON roadmap_nodes(node_key)"
            )
        )
        session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS node_progress (
                  roadmap_slug TEXT NOT NULL,
                  user_id TEXT NOT NULL,
                  node_id TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'not_started',
                  updated_at TIMESTAMPTZ DEFAULT NOW(),
                  PRIMARY KEY (roadmap_slug, user_id, node_id),
                  CONSTRAINT chk_node_progress_status CHECK (status IN ('not_started', 'in_progress', 'completed'))
                )
                """
            )
        )
        session.execute(
            text("ALTER TABLE node_progress ADD COLUMN IF NOT EXISTS roadmap_slug TEXT")
        )
        session.execute(
            text("UPDATE node_progress SET roadmap_slug = COALESCE(NULLIF(roadmap_slug, ''), 'generated')")
        )
        session.execute(
            text("CREATE INDEX IF NOT EXISTS node_progress_slug_user_idx ON node_progress(roadmap_slug, user_id)")
        )

        session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS videos (
                  video_id TEXT PRIMARY KEY,
                  title TEXT,
                  channel TEXT,
                  views BIGINT DEFAULT 0,
                  likes BIGINT DEFAULT 0,
                  duration TEXT,
                  thumbnail TEXT,
                  source_roadmap TEXT,
                  created_at TIMESTAMPTZ DEFAULT NOW(),
                  updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        # Backward-compatible migrations for environments that already have a legacy videos table.
        session.execute(text("ALTER TABLE videos ADD COLUMN IF NOT EXISTS source_roadmap TEXT"))
        session.execute(
            text("ALTER TABLE videos ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()")
        )
        session.execute(
            text("ALTER TABLE videos ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()")
        )
        session.execute(text("UPDATE videos SET created_at = COALESCE(created_at, NOW())"))
        session.execute(text("UPDATE videos SET updated_at = COALESCE(updated_at, NOW())"))

        session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS node_video_mapping (
                  id SERIAL PRIMARY KEY,
                  node_id TEXT NOT NULL,
                  video_id TEXT NOT NULL,
                  score INT DEFAULT 10,
                  rank INT,
                  created_at TIMESTAMPTZ DEFAULT NOW(),
                  UNIQUE(node_id, video_id)
                )
                """
            )
        )
        session.execute(text("ALTER TABLE node_video_mapping ADD COLUMN IF NOT EXISTS score INT DEFAULT 10"))
        session.execute(text("ALTER TABLE node_video_mapping ADD COLUMN IF NOT EXISTS rank INT"))
        session.execute(
            text("ALTER TABLE node_video_mapping ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()")
        )
        session.execute(
            text(
                """
                DELETE FROM node_video_mapping a
                USING node_video_mapping b
                WHERE a.ctid < b.ctid
                  AND a.node_id = b.node_id
                  AND a.video_id = b.video_id
                """
            )
        )
        session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS node_video_mapping_node_video_ux ON node_video_mapping(node_id, video_id)"
            )
        )
        session.execute(
            text("CREATE INDEX IF NOT EXISTS node_video_mapping_node_idx ON node_video_mapping(node_id)")
        )

    def save_employee(self, profile: dict) -> int:
        session = self.session_factory()
        try:
            count = session.query(Employee).count()
            role = profile.get("role", "Employee")
            safe_role = role.replace(" ", "_").lower()
            generated_name = f"{role} Candidate {count + 1}"
            employee = Employee(
                name=profile.get("name", generated_name),
                email=profile.get("email", f"{safe_role}_{uuid.uuid4().hex[:8]}@example.com")
            )
            session.add(employee)

            skills = [str(s).strip().lower() for s in profile.get("skills", []) if str(s).strip()]
            if skills:
                session.flush()
                for skill_name in skills:
                    skill = session.query(Skill).filter(Skill.name == skill_name).first()
                    if not skill:
                        skill = Skill(name=skill_name, category="technical")
                        session.add(skill)
                        session.flush()

                    existing_link = (
                        session.query(EmployeeSkill)
                        .filter(
                            EmployeeSkill.employee_id == employee.id,
                            EmployeeSkill.skill_id == skill.id,
                        )
                        .first()
                    )
                    if not existing_link:
                        session.add(
                            EmployeeSkill(
                                employee_id=employee.id,
                                skill_id=skill.id,
                                proficiency=1.0,
                            )
                        )

            session.commit()
            return employee.id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def save_analyses(self, employee_id: int, readiness_score: float, core_gaps: list, market_gaps: list) -> int:
        session = self.session_factory()
        try:
            analysis = Analysis(
                employee_id=employee_id,
                readiness_score=readiness_score,
                core_gaps=core_gaps,
                market_gaps=market_gaps
            )
            session.add(analysis)
            session.commit()
            return analysis.id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def save_roadmap(self, employee_id: int, roadmap: dict) -> int:
        session = self.session_factory()
        try:
            db_roadmap = Roadmap(
                employee_id=employee_id,
                foundation=roadmap.get("foundation", []),
                core=roadmap.get("core", []),
                projects=roadmap.get("projects", []),
                advanced=roadmap.get("advanced", [])
            )
            session.add(db_roadmap)
            session.commit()
            return db_roadmap.id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def sync_roadmap_nodes(self, roadmap: dict[str, Any], user_email: str = None) -> int:
        """Persist generated roadmap nodes into roadmap_nodes, scoped per user."""
        session = self.session_factory()
        try:
            self._ensure_roadmap_tracking_tables(session)

            roadmap_slug = str(
                roadmap.get("metadata", {}).get("roadmap_slug")
                or roadmap.get("roadmap_id")
                or "generated"
            ).strip() or "generated"

            roadmap_title = str(roadmap.get("roadmap_title") or roadmap_slug)
            role = str(roadmap.get("metadata", {}).get("target_role") or "")

            # ✅ Step 1 — Collect existing node_ids for this slug FIRST
            existing_node_ids_result = session.execute(
                text("""
                    SELECT node_id FROM roadmap_nodes
                    WHERE roadmap_slug = :roadmap_slug
                """),
                {"roadmap_slug": roadmap_slug},
            ).fetchall()

            existing_node_ids = [row[0] for row in existing_node_ids_result]

            # ✅ Step 2 — Delete node_video_mapping FIRST using collected IDs
            if existing_node_ids:
                session.execute(
                    text("""
                        DELETE FROM node_video_mapping
                        WHERE node_id = ANY(:node_ids)
                    """),
                    {"node_ids": existing_node_ids},
                )

            # ✅ Step 3 — Delete node_progress
            session.execute(
                text("DELETE FROM node_progress WHERE roadmap_slug = :roadmap_slug"),
                {"roadmap_slug": roadmap_slug},
            )

            # ✅ Step 4 — NOW safe to delete roadmap_nodes (no FK references left)
            session.execute(
                text("DELETE FROM roadmap_nodes WHERE roadmap_slug = :roadmap_slug"),
                {"roadmap_slug": roadmap_slug},
            )

            # ✅ Step 5 — Flush so deletes are visible before inserts
            session.flush()

            # ✅ Step 6 — Insert new nodes
            stored = 0
            for phase in roadmap.get("phases", []):
                phase_id    = str(phase.get("phase_id")    or "")
                phase_title = str(phase.get("phase_title") or "")

                for node in phase.get("nodes", []):
                    source_node_id = str(
                        node.get("original_node_id") or node.get("node_id") or ""
                    ).strip()
                    if not source_node_id:
                        continue

                    node_id  = str(node.get("node_id") or source_node_id).strip()
                    node_key = f"{roadmap_slug}::{source_node_id}"
                    title     = str(node.get("label") or node.get("title") or source_node_id)
                    node_type = str(node.get("type")     or "")
                    category  = str(node.get("category") or "")

                    session.execute(
                        text("""
                            INSERT INTO roadmap_nodes (
                                node_key, roadmap_slug, roadmap_title, node_id, source_node_id,
                                title, role, node_type, phase_id, phase_title, category,
                                raw_node, source_file
                            )
                            VALUES (
                                :node_key, :roadmap_slug, :roadmap_title, :node_id, :source_node_id,
                                :title, :role, :node_type, :phase_id, :phase_title, :category,
                                CAST(:raw_node AS JSONB), :source_file
                            )
                            ON CONFLICT (node_key) DO UPDATE
                            SET
                                roadmap_slug   = EXCLUDED.roadmap_slug,
                                roadmap_title  = EXCLUDED.roadmap_title,
                                node_id        = EXCLUDED.node_id,
                                source_node_id = EXCLUDED.source_node_id,
                                title          = EXCLUDED.title,
                                role           = EXCLUDED.role,
                                node_type      = EXCLUDED.node_type,
                                phase_id       = EXCLUDED.phase_id,
                                phase_title    = EXCLUDED.phase_title,
                                category       = EXCLUDED.category,
                                raw_node       = EXCLUDED.raw_node,
                                source_file    = EXCLUDED.source_file,
                                updated_at     = NOW()
                        """),
                        {
                            "node_key":       node_key,
                            "roadmap_slug":   roadmap_slug,
                            "roadmap_title":  roadmap_title,
                            "node_id":        node_id,
                            "source_node_id": source_node_id,
                            "title":          title,
                            "role":           role,
                            "node_type":      node_type,
                            "phase_id":       phase_id,
                            "phase_title":    phase_title,
                            "category":       category,
                            "raw_node":       json.dumps(node),
                            "source_file":    "src.main:/generate/roadmap",
                        },
                    )
                    stored += 1

            session.commit()
            return stored

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            

    def upsert_node_progress(self, roadmap_slug: str, user_id: str, node_id: str, status: str) -> bool:
        session = self.session_factory()
        try:
            self._ensure_roadmap_tracking_tables(session)
            resolved_slug = str(roadmap_slug or "").strip() or "generated"
            exists = session.execute(
                text(
                    """
                    SELECT 1
                    FROM roadmap_nodes
                    WHERE roadmap_slug = :roadmap_slug AND node_id = :node_id
                    LIMIT 1
                    """
                ),
                {"roadmap_slug": resolved_slug, "node_id": node_id},
            ).scalar()

            if not exists:
                fallback_slug = session.execute(
                    text(
                        """
                        SELECT roadmap_slug
                        FROM roadmap_nodes
                        WHERE node_id = :node_id
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """
                    ),
                    {"node_id": node_id},
                ).scalar()
                if fallback_slug:
                    resolved_slug = str(fallback_slug)
                    exists = True

            if not exists:
                return False

            updated = session.execute(
                text(
                    """
                    UPDATE node_progress
                    SET status = :status,
                        updated_at = NOW(),
                        roadmap_slug = :roadmap_slug
                    WHERE roadmap_slug = :roadmap_slug
                      AND user_id = :user_id
                      AND node_id = :node_id
                    """
                ),
                {
                    "roadmap_slug": resolved_slug,
                    "user_id": user_id,
                    "node_id": node_id,
                    "status": status,
                },
            )
            if updated.rowcount == 0:
                session.execute(
                    text(
                        """
                        INSERT INTO node_progress (roadmap_slug, user_id, node_id, status)
                        VALUES (:roadmap_slug, :user_id, :node_id, :status)
                        """
                    ),
                    {
                        "roadmap_slug": resolved_slug,
                        "user_id": user_id,
                        "node_id": node_id,
                        "status": status,
                    },
                )
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            
    def get_videos_by_node_id(self, node_id: str) -> list[dict[str, Any]]:
        """
        Fetch cached videos for a node_id shared across all users.
        Returns videos in the same format as format_videos() so they can be
        passed directly into upsert_node_videos() without transformation.
        """
        session = self.session_factory()
        try:
            rows = session.execute(
                text(
                    """
                    SELECT v.video_id, v.title, v.channel, v.thumbnail, m.score, m.rank
                    FROM node_video_mapping m
                    JOIN videos v ON v.video_id = m.video_id
                    WHERE m.node_id = :node_id
                    ORDER BY m.rank ASC NULLS LAST, m.score DESC
                    LIMIT 10
                    """
                ),
                {"node_id": node_id},
            ).fetchall()

            if not rows:
                return []  # ← No cache; caller will fetch from YouTube

            return [
                {
                    "video_id":  str(row.video_id  or ""),
                    "title":     str(row.title     or ""),
                    "channel":   str(row.channel   or ""),
                    "thumbnail": str(row.thumbnail or ""),
                    "score":     int(row.score or 10),
                }
                for row in rows
                if str(row.video_id or "").strip()
            ]
        except Exception:
            logger.exception("[CACHE] Failed to fetch cached videos for node_id=%s", node_id)
            return []  # ← Safe fallback: triggers fresh YouTube fetch
        finally:
            session.close()

    def _resolve_requested_roadmap_slug(
        self,
        session,
        roadmap_slug: str,
        user_id: str | None = None,          # ✅ NEW
    ) -> str:
        resolved_slug = str(roadmap_slug or "").strip() or "generated"
        if resolved_slug != "generated":
            return resolved_slug

        # ✅ If we know the user, find THEIR slug specifically
        if user_id:
            user_slug = session.execute(
                text(
                    """
                    SELECT rn.roadmap_slug
                    FROM roadmap_nodes rn
                    WHERE rn.roadmap_slug IS NOT NULL
                    AND rn.roadmap_slug <> ''
                    AND rn.roadmap_slug ILIKE :user_pattern
                    ORDER BY MAX(rn.updated_at) DESC
                    GROUP BY rn.roadmap_slug
                    LIMIT 1
                    """
                ),
                {"user_pattern": f"%{user_id.replace('@', '-at-').replace('.', '-')}%"},
            ).scalar()

            if user_slug:
                return str(user_slug)

        # ✅ Fallback — check node_progress for this user's slug
        if user_id:
            progress_slug = session.execute(
                text(
                    """
                    SELECT roadmap_slug
                    FROM node_progress
                    WHERE user_id = :user_id
                    AND roadmap_slug IS NOT NULL
                    AND roadmap_slug <> ''
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                ),
                {"user_id": user_id},
            ).scalar()

            if progress_slug:
                return str(progress_slug)

        # ⚠️ Last resort — global latest (old behavior)
        latest_slug = session.execute(
            text(
                """
                SELECT roadmap_slug
                FROM roadmap_nodes
                WHERE roadmap_slug IS NOT NULL AND roadmap_slug <> ''
                GROUP BY roadmap_slug
                ORDER BY MAX(updated_at) DESC
                LIMIT 1
                """
            )
        ).scalar()
        return str(latest_slug or resolved_slug)

    def get_roadmap_progress_from_db(self, roadmap_slug: str, user_id: str) -> dict[str, Any]:
        session = self.session_factory()
        try:
            self._ensure_roadmap_tracking_tables(session)
            resolved_slug = self._resolve_requested_roadmap_slug(session, roadmap_slug, user_id)

            rows = session.execute(
                text(
                    """
                    SELECT rn.node_id, COALESCE(np.status, 'not_started') AS status
                    FROM roadmap_nodes rn
                    LEFT JOIN node_progress np
                      ON np.roadmap_slug = rn.roadmap_slug
                     AND np.user_id = :user_id
                     AND np.node_id = rn.node_id
                    WHERE rn.roadmap_slug = :roadmap_slug
                    ORDER BY rn.node_id ASC
                    """
                ),
                {"roadmap_slug": resolved_slug, "user_id": user_id},
            ).fetchall()
            logger.warning(
            "[DEBUG PROGRESS] total rows=%d completed=%d for slug='%s'",
            len(rows),
            sum(1 for r in rows if r.status == "completed"),
            resolved_slug,
            )
            total = len(rows)
            completed = sum(1 for row in rows if row.status == "completed")
            in_progress = sum(1 for row in rows if row.status == "in_progress")
            not_started = total - completed - in_progress
            completion_rate = round((completed / total * 100), 1) if total else 0.0

            return {
                "roadmap_slug": resolved_slug,
                "user_id": user_id,
                "total": total,
                "completed": completed,
                "in_progress": in_progress,
                "not_started": not_started,
                "completion_rate": completion_rate,
            }
        finally:
            session.close()

    def get_roadmap_skills_from_db(
        self,
        roadmap_slug: str,
        user_id: str,
        node_status_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Return roadmap skills/nodes grouped from roadmap_nodes table."""
        session = self.session_factory()
        overrides = node_status_overrides or {}
        try:
            self._ensure_roadmap_tracking_tables(session)
            resolved_slug = self._resolve_requested_roadmap_slug(session, roadmap_slug, user_id)

            def _fetch_rows(slug: str):
                return session.execute(
                    text(
                        """
                        SELECT node_id, title, node_type, phase_title, category, raw_node
                        FROM roadmap_nodes
                        WHERE roadmap_slug = :slug
                        ORDER BY phase_title ASC, node_id ASC
                        """
                    ),
                    {"slug": slug},
                ).fetchall()

            rows = _fetch_rows(resolved_slug)

            if not rows:
                return {"roadmap_slug": resolved_slug, "user_id": user_id, "skills": []}

            progress_rows = session.execute(
                text(
                    """
                    SELECT node_id, status
                    FROM node_progress
                    WHERE roadmap_slug = :roadmap_slug AND user_id = :user_id
                    """
                ),
                {"roadmap_slug": resolved_slug, "user_id": user_id},
            ).fetchall()
            persisted_statuses = {str(row.node_id): str(row.status) for row in progress_rows}

            skill_map: dict[str, dict[str, Any]] = {}
            for row in rows:
                node_id = str(row.node_id or "")
                raw_node = row.raw_node if isinstance(row.raw_node, dict) else {}
                if not isinstance(raw_node, dict):
                    raw_node = {}

                skill_name = str(
                    raw_node.get("matched_skill")
                    or row.phase_title
                    or row.category
                    or "General"
                )
                if skill_name not in skill_map:
                    skill_map[skill_name] = {"skill": skill_name, "nodes": []}

                store_key = f"{resolved_slug}:{user_id}:{node_id}"
                fallback_store_key = f"{roadmap_slug}:{user_id}:{node_id}"
                status = (
                    overrides.get(store_key)
                    or overrides.get(fallback_store_key)
                    or persisted_statuses.get(node_id)
                    or str(raw_node.get("status") or "not_started")
                )

                skill_map[skill_name]["nodes"].append(
                    {
                        "node_id": node_id,
                        "title": str(row.title or raw_node.get("label") or node_id),
                        "status": status,
                        "type": str(row.node_type or raw_node.get("type") or ""),
                        "importance": str(raw_node.get("importance") or ""),
                        "phase_title": str(row.phase_title or raw_node.get("phase_title") or ""),
                        "depends_on": raw_node.get("depends_on", []),
                    }
                )

            skills = []
            for skill_name, data in skill_map.items():
                nodes = data["nodes"]
                completed = sum(1 for n in nodes if n["status"] == "completed")
                skills.append(
                    {
                        "skill": skill_name,
                        "total": len(nodes),
                        "completed": completed,
                        "nodes": nodes,
                    }
                )

            return {"roadmap_slug": resolved_slug, "user_id": user_id, "skills": skills}
        finally:
            session.close()

    def upsert_node_videos(self, roadmap_slug: str, node_id: str, videos: list[dict[str, Any]]) -> int:
        """Persist YouTube videos for a roadmap node using videos + node_video_mapping tables."""
        session = self.session_factory()
        try:
            self._ensure_roadmap_tracking_tables(session)

            # Clear old mappings for this node so rank/order can be refreshed.
            session.execute(
                text("DELETE FROM node_video_mapping WHERE node_id = :node_id"),
                {"node_id": node_id},
            )

            stored = 0
            for rank, video in enumerate(videos, start=1):
                video_id = str(video.get("video_id") or "").strip()
                if not video_id:
                    continue

                session.execute(
                    text(
                        """
                        INSERT INTO videos (
                            video_id, title, channel, views, likes, duration,
                            thumbnail, source_roadmap, updated_at
                        )
                        VALUES (
                            :video_id, :title, :channel, 0, 0, '',
                            :thumbnail, :source_roadmap, NOW()
                        )
                        ON CONFLICT (video_id) DO UPDATE
                        SET title = EXCLUDED.title,
                            channel = EXCLUDED.channel,
                            thumbnail = EXCLUDED.thumbnail,
                            source_roadmap = COALESCE(EXCLUDED.source_roadmap, videos.source_roadmap),
                            updated_at = NOW()
                        """
                    ),
                    {
                        "video_id": video_id,
                        "title": str(video.get("title") or ""),
                        "channel": str(video.get("channel") or ""),
                        "thumbnail": str(video.get("thumbnail") or ""),
                        "source_roadmap": roadmap_slug,
                    },
                )

                session.execute(
                    text(
                        """
                        INSERT INTO node_video_mapping (node_id, video_id, score, rank)
                        VALUES (:node_id, :video_id, :score, :rank)
                        ON CONFLICT (node_id, video_id) DO UPDATE
                        SET score = EXCLUDED.score,
                            rank = EXCLUDED.rank
                        """
                    ),
                    {
                        "node_id": node_id,
                        "video_id": video_id,
                        "score": int(video.get("score", 10)),
                        "rank": rank,
                    },
                )
                stored += 1

            session.commit()
            return stored
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_node_videos(self, roadmap_slug: str, node_id: str, lookup_node_id: str | None = None) -> list[dict[str, Any]]:
        """Fetch videos for a node from node_video_mapping joined with videos."""
        session = self.session_factory()
        try:
            normalized_lookup = str(lookup_node_id or "").strip()
            if normalized_lookup and normalized_lookup != node_id:
                rows = session.execute(
                    text(
                        """
                        SELECT v.video_id, v.title, v.channel, v.thumbnail, m.score, m.rank
                        FROM node_video_mapping m
                        JOIN videos v ON v.video_id = m.video_id
                        WHERE m.node_id = :node_id OR m.node_id = :lookup_node_id
                        ORDER BY m.rank ASC NULLS LAST, m.score DESC
                        """
                    ),
                    {"node_id": node_id, "lookup_node_id": normalized_lookup},
                ).fetchall()
            else:
                rows = session.execute(
                    text(
                        """
                        SELECT v.video_id, v.title, v.channel, v.thumbnail, m.score, m.rank
                        FROM node_video_mapping m
                        JOIN videos v ON v.video_id = m.video_id
                        WHERE m.node_id = :node_id
                        ORDER BY m.rank ASC NULLS LAST, m.score DESC
                        """
                    ),
                    {"node_id": node_id},
                ).fetchall()

            seen: set[str] = set()
            videos: list[dict[str, Any]] = []
            for row in rows:
                video_id = str(row.video_id or "")
                if not video_id or video_id in seen:
                    continue
                seen.add(video_id)
                videos.append(
                    {
                        "video_id": video_id,
                        "title": str(row.title or ""),
                        "channel": str(row.channel or ""),
                        "thumbnail": str(row.thumbnail or ""),
                        "score": int(row.score or 10),
                        "rank": int(row.rank) if row.rank else None,
                        "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
                    }
                )
            return videos
        finally:
            session.close()

    def search_videos_catalog(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search existing videos table by query text as a fallback when YouTube API is unavailable."""
        session = self.session_factory()
        try:
            normalized = str(query or "").strip()
            if not normalized:
                return []

            pattern = f"%{normalized}%"
            try:
                rows = session.execute(
                    text(
                        """
                        SELECT video_id, title, channel, thumbnail
                        FROM videos
                        WHERE title ILIKE :pattern OR channel ILIKE :pattern
                        ORDER BY COALESCE(views, 0) DESC, COALESCE(likes, 0) DESC,
                                 COALESCE(created_at, NOW()) DESC, video_id DESC
                        LIMIT :limit
                        """
                    ),
                    {"pattern": pattern, "limit": int(limit)},
                ).fetchall()
            except Exception as exc:
                logger.warning("search_videos_catalog query failed for pattern=%s: %s", pattern, exc)
                return []

            return [
                {
                    "video_id": str(row.video_id or ""),
                    "title": str(row.title or ""),
                    "channel": str(row.channel or ""),
                    "thumbnail": str(row.thumbnail or ""),
                    "score": 10,
                }
                for row in rows
                if str(row.video_id or "").strip()
            ]
        finally:
            session.close()

    # ── Skill promotion helpers ─────────────────────────────────────────────

    def add_employee_skill(self, user_id: str, skill_name: str) -> bool:
        """
        Add *skill_name* to an employee's profile (employee_skills table).

        Looks up the employee by email or siemens_id (both stored as user_id
        when users register via auth).  Skips gracefully if already present.

        Returns True when a new skill was added, False when skipped.
        """
        session = self.session_factory()
        try:
            # Resolve employee by email or siemens_id
            employee = (
                session.query(Employee).filter(Employee.email == user_id).first()
                or session.query(Employee).filter(Employee.siemens_id == user_id).first()
            )
            if not employee:
                logger.warning("[SKILL PROMOTE] No employee found for user_id=%s", user_id)
                return False

            normalized = skill_name.strip().lower()
            if not normalized:
                return False

            # Ensure skill row exists
            skill = session.query(Skill).filter(Skill.name == normalized).first()
            if not skill:
                skill = Skill(name=normalized, category="technical")
                session.add(skill)
                session.flush()

            # Check whether link already exists
            existing = (
                session.query(EmployeeSkill)
                .filter(
                    EmployeeSkill.employee_id == employee.id,
                    EmployeeSkill.skill_id == skill.id,
                )
                .first()
            )
            if existing:
                return False  # already present

            session.add(
                EmployeeSkill(
                    employee_id=employee.id,
                    skill_id=skill.id,
                    proficiency=1.0,
                )
            )
            session.commit()
            logger.info(
                "[SKILL PROMOTE] Added skill '%s' to employee '%s'",
                normalized,
                user_id,
            )
            return True
        except Exception:
            session.rollback()
            logger.exception(
                "[SKILL PROMOTE] Failed to add skill '%s' for user_id=%s",
                skill_name,
                user_id,
            )
            return False
        finally:
            session.close()

    def check_and_promote_skill(self, roadmap_slug: str, user_id: str, node_id: str) -> str | None:
        """
        After a node status update, check whether ALL nodes in the same
        skill/phase group are now completed.  If so, promote that skill to
        the employee's profile and return the promoted skill name.

        Returns the skill name that was promoted, or None.
        """
        session = self.session_factory()
        try:
            resolved_slug = self._resolve_requested_roadmap_slug(session, roadmap_slug, user_id)

            # 1. Find the phase_title (= skill group) of the updated node
            phase_row = session.execute(
                text(
                    """
                    SELECT phase_title, raw_node
                    FROM roadmap_nodes
                    WHERE roadmap_slug = :slug AND node_id = :node_id
                    LIMIT 1
                    """
                ),
                {"slug": resolved_slug, "node_id": node_id},
            ).fetchone()

            if not phase_row:
                return None

            raw_node = phase_row.raw_node if isinstance(phase_row.raw_node, dict) else {}
            skill_group = (
                raw_node.get("matched_skill")
                or phase_row.phase_title
                or raw_node.get("phase_title")
            )
            if not skill_group:
                return None

            # 2. Fetch all node_ids in this skill group
            all_nodes = session.execute(
                text(
                    """
                    SELECT rn.node_id
                    FROM roadmap_nodes rn
                    WHERE rn.roadmap_slug = :slug
                      AND (
                            rn.phase_title = :skill_group
                            OR (rn.raw_node->>'matched_skill') = :skill_group
                          )
                    """
                ),
                {"slug": resolved_slug, "skill_group": skill_group},
            ).fetchall()

            all_node_ids = {str(r.node_id) for r in all_nodes}
            if not all_node_ids:
                return None

            # 3. Count completed nodes for this user in this group
            completed_rows = session.execute(
                text(
                    """
                    SELECT node_id
                    FROM node_progress
                    WHERE roadmap_slug = :slug
                      AND user_id     = :user_id
                      AND status      = 'completed'
                      AND node_id     = ANY(:node_ids)
                    """
                ),
                {
                    "slug": resolved_slug,
                    "user_id": user_id,
                    "node_ids": list(all_node_ids),
                },
            ).fetchall()

            completed_ids = {str(r.node_id) for r in completed_rows}

            if all_node_ids.issubset(completed_ids):
                # All nodes complete — promote the skill
                added = self.add_employee_skill(user_id, skill_group)
                if added:
                    return skill_group
            return None
        except Exception:
            logger.exception(
                "[SKILL PROMOTE] check_and_promote_skill failed: slug=%s user=%s node=%s",
                roadmap_slug,
                user_id,
                node_id,
            )
            return None
        finally:
            session.close()

    # ── Employee / talent helpers ────────────────────────────────────────────

    def get_employee_count(self) -> int:
        session = self.session_factory()
        try:
            return session.query(Employee).count()
        finally:
            session.close()
    def get_employee_profiles(self) -> list[dict]:
        """
        Fetch all employee profiles with their skills.
        Uses the same proven join logic as get_user_profile_by_email().
        """
        session = self.session_factory()
        try:
            employees = session.query(Employee).all()
            profiles = []

            for employee in employees:
                # ✅ Exact same join that works in get_user_profile_by_email
                employee_skills = (
                    session.query(Skill.name)
                    .join(EmployeeSkill, Skill.id == EmployeeSkill.skill_id)
                    .filter(EmployeeSkill.employee_id == employee.id)
                    .all()
                )

                skill_names = [skill_name for (skill_name,) in employee_skills]

                profiles.append({
                    "id":     employee.id,
                    "name":   employee.name,
                    "skills": skill_names,
                })

            return profiles
        finally:
            session.close()

    def save_job_description(self, description: str, title: str = "Uploaded Job Description") -> int:
        session = self.session_factory()
        try:
            jd = JobDescription(title=title, description=description, required_skills=[])
            session.add(jd)
            session.commit()
            return jd.id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def save_talent_matches(self, job_description_id: int, matches: list[dict]) -> int:
        session = self.session_factory()
        created = 0
        try:
            for match in matches:
                employee_name = match.get("employee")
                employee = (
                    session.query(Employee)
                    .filter(Employee.name == employee_name)
                    .first()
                )
                if not employee:
                    continue
                db_match = TalentMatch(
                    job_description_id=job_description_id,
                    employee_id=employee.id,
                    match_score=match.get("score", 0.0),
                )
                session.add(db_match)
                created += 1

            session.commit()
            return created
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def ping(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception as exc:
            logger.error(f"Database ping failed: {exc}")
            return False

    def upsert_user_profile(self, profile: dict) -> dict:
        session = self.session_factory()
        try:
            siemens_id = profile.get("siemens_id", "")
            email = profile.get("email", "")
            employee = None

            if siemens_id:
                employee = session.query(Employee).filter(Employee.siemens_id == siemens_id).first()
            if not employee and email:
                employee = session.query(Employee).filter(Employee.email == email).first()

            if employee:
                for field in ("name", "department", "role", "experience_years"):
                    if field in profile and profile[field] is not None:
                        setattr(employee, field, profile[field])
                if siemens_id and not employee.siemens_id:
                    employee.siemens_id = siemens_id
                if email and not employee.email:
                    employee.email = email
                employee_id = employee.id
            else:
                count = session.query(Employee).count()
                role = profile.get("role") or "Employee"
                safe_role = role.replace(" ", "_").lower()
                employee = Employee(
                    name=profile.get("name", f"{role} Candidate {count + 1}"),
                    email=email or f"{safe_role}_{uuid.uuid4().hex[:8]}@example.com",
                    siemens_id=siemens_id or None,
                    department=profile.get("department"),
                    role=role,
                    experience_years=profile.get("experience_years"),
                )
                session.add(employee)
                session.flush()
                employee_id = employee.id

            skills = [str(s).strip().lower() for s in profile.get("skills", []) if str(s).strip()]
            if skills:
                for skill_name in skills:
                    skill = session.query(Skill).filter(Skill.name == skill_name).first()
                    if not skill:
                        skill = Skill(name=skill_name, category="technical")
                        session.add(skill)
                        session.flush()
                    existing_link = (
                        session.query(EmployeeSkill)
                        .filter(
                            EmployeeSkill.employee_id == employee_id,
                            EmployeeSkill.skill_id == skill.id,
                        )
                        .first()
                    )
                    if not existing_link:
                        session.add(
                            EmployeeSkill(
                                employee_id=employee_id,
                                skill_id=skill.id,
                                proficiency=1.0,
                            )
                        )

            session.commit()
            result = {
                "id": employee_id,
                "name": employee.name,
                "email": employee.email,
                "siemens_id": employee.siemens_id,
                "department": employee.department,
                "role": employee.role,
                "experience_years": employee.experience_years,
                "skills": skills,
                "created_at": employee.created_at.isoformat() if employee.created_at else "",
                "updated_at": datetime.now(UTC).isoformat(),
            }
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_user_profile_by_email(self, email: str) -> dict | None:
        session = self.session_factory()
        try:
            employee = session.query(Employee).filter(Employee.email == email).first()
            if not employee:
                return None
            employee_skills = (
                session.query(Skill.name)
                .join(EmployeeSkill, Skill.id == EmployeeSkill.skill_id)
                .filter(EmployeeSkill.employee_id == employee.id)
                .all()
            )
            return {
                "id": employee.id,
                "name": employee.name,
                "email": employee.email,
                "siemens_id": employee.siemens_id,
                "department": employee.department,
                "role": employee.role,
                "experience_years": employee.experience_years,
                "skills": [skill_name for (skill_name,) in employee_skills],
                "created_at": employee.created_at.isoformat() if employee.created_at else "",
            }
        finally:
            session.close()

    def get_user_profile_by_siemens_id(self, siemens_id: str) -> dict | None:
        session = self.session_factory()
        try:
            employee = session.query(Employee).filter(Employee.siemens_id == siemens_id).first()
            if not employee:
                return None
            employee_skills = (
                session.query(Skill.name)
                .join(EmployeeSkill, Skill.id == EmployeeSkill.skill_id)
                .filter(EmployeeSkill.employee_id == employee.id)
                .all()
            )
            return {
                "id": employee.id,
                "name": employee.name,
                "email": employee.email,
                "siemens_id": employee.siemens_id,
                "department": employee.department,
                "role": employee.role,
                "experience_years": employee.experience_years,
                "skills": [skill_name for (skill_name,) in employee_skills],
                "created_at": employee.created_at.isoformat() if employee.created_at else "",
            }
        finally:
            session.close()

    def get_user_by_email(self, email: str) -> User | None:
        session = self.session_factory()
        try:
            return session.query(User).filter(User.email == email).first()
        finally:
            session.close()

    def get_user_by_siemens_id(self, siemens_id: str) -> User | None:
        session = self.session_factory()
        try:
            return session.query(User).filter(User.siemens_id == siemens_id).first()
        finally:
            session.close()

    def create_user(self, email: str, password: str, siemens_id: str | None = None, name: str | None = None, department: str | None = None, role: str | None = None, experience_years: int = 0, skills: list | None = None) -> User:
        session = self.session_factory()
        try:
            user = User(
                email=email,
                siemens_id=siemens_id,
                password_hash=hash_password(password),
                name=name,
                department=department,
                role=role,
                experience_years=experience_years,
                skills=skills or [],
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            return user
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def upsert_user(self, email: str, password: str | None = None, siemens_id: str | None = None, name: str | None = None, department: str | None = None, role: str | None = None, experience_years: int = 0, skills: list | None = None) -> User:
        session = self.session_factory()
        try:
            user = session.query(User).filter(User.email == email).first()
            if not user and siemens_id:
                user = session.query(User).filter(User.siemens_id == siemens_id).first()
            if user:
                if password:
                    user.password_hash = hash_password(password)
                if name:
                    user.name = name
                if department is not None:
                    user.department = department
                if role is not None:
                    user.role = role
                if experience_years:
                    user.experience_years = experience_years
                if skills is not None:
                    user.skills = skills
                session.commit()
                session.refresh(user)
            else:
                user = User(
                    email=email,
                    siemens_id=siemens_id,
                    password_hash=hash_password(password or uuid.uuid4().hex),
                    name=name,
                    department=department,
                    role=role,
                    experience_years=experience_years,
                    skills=skills or [],
                )
                session.add(user)
                session.commit()
                session.refresh(user)
            return user
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def store_user_roadmap(
        self,
        user_id: int,
        roadmap_slug: str,
        user_email: str = None       # ✅ NEW parameter
    ) -> bool:
        """Store which roadmap a user is currently working on."""
        session = self.session_factory()
        try:
            employee = session.query(Employee).filter(Employee.id == user_id).first()
            if not employee:
                return False

            # ✅ Store user-specific slug (already contains email in slug)
            employee.current_roadmap_slug = roadmap_slug

            # ✅ Also store email on employee record if column exists
            if user_email and hasattr(employee, "email"):
                employee.email = user_email

            session.commit()
            logger.info(
                f"[PERSISTENCE] Stored roadmap_slug '{roadmap_slug}' "
                f"for user_id={user_id} email={user_email}"
            )
            return True

        except Exception as e:
            session.rollback()
            logger.exception(
                f"[PERSISTENCE] Failed to store roadmap for user_id={user_id}: {e}"
            )
            return False
        finally:
            session.close()
    def get_user_roadmap_with_progress(self, user_id: int) -> dict | None:
        """Get user's current roadmap slug and all their progress on it."""
        session = self.session_factory()
        try:
            employee = session.query(Employee).filter(Employee.id == user_id).first()
            if not employee:
                return None

            # Use the stored roadmap slug; fall back to the latest generated roadmap
            roadmap_slug = employee.current_roadmap_slug
            if not roadmap_slug:
                row = session.execute(
                    text(
                        """
                        SELECT roadmap_slug FROM roadmap_nodes
                        WHERE roadmap_slug IS NOT NULL AND roadmap_slug <> ''
                        GROUP BY roadmap_slug ORDER BY MAX(updated_at) DESC LIMIT 1
                        """
                    )
                ).scalar()
                roadmap_slug = row or None
            if not roadmap_slug:
                return None

            # node_progress stores email (learning_users.user_id) as user_id
            progress_user_id = employee.email or str(user_id)

            # Fetch all nodes in this roadmap
            nodes_result = session.execute(
                text(
                    """
                    SELECT node_id, phase_title, title, node_type
                    FROM roadmap_nodes
                    WHERE roadmap_slug = :slug
                    ORDER BY phase_title, node_id
                    """
                ),
                {"slug": roadmap_slug},
            ).fetchall()

            # Fetch progress for all nodes — keyed by email
            progress_result = session.execute(
                text(
                    """
                    SELECT node_id, status
                    FROM node_progress
                    WHERE roadmap_slug = :slug AND user_id = :user_id
                    """
                ),
                {"slug": roadmap_slug, "user_id": progress_user_id},
            ).fetchall()
            
            progress_map = {row.node_id: row.status for row in progress_result}
            
            # Build nodes with status
            nodes = []
            for row in nodes_result:
                status = progress_map.get(row.node_id, "not_started")
                nodes.append({
                    "node_id": row.node_id,
                    "title": row.title or row.node_id,
                    "phase_title": row.phase_title,
                    "node_type": row.node_type,
                    "status": status,
                })
            
            # Calculate progress stats
            total = len(nodes)
            completed = sum(1 for n in nodes if n["status"] == "completed")
            in_progress = sum(1 for n in nodes if n["status"] == "in_progress")
            
            return {
                "roadmap_slug": roadmap_slug,
                "user_id": user_id,
                "nodes": nodes,
                "total": total,
                "completed": completed,
                "in_progress": in_progress,
                "not_started": total - completed - in_progress,
                "completion_rate": round((completed / total * 100), 1) if total > 0 else 0.0,
            }
        except Exception as e:
            logger.exception(f"[PERSISTENCE] Failed to get roadmap for user_id {user_id}: {e}")
            return None
        finally:
            session.close()
    
    def get_all_employee_profiles(self) -> list[dict]:
        """
        Reuses the same logic as get_user_profile_by_email but fetches ALL employees at once.
        """
        session = self.session_factory()
        try:
            employees = session.query(Employee).all()
            profiles = []

            for employee in employees:
                # ✅ Reuse exact same skill fetch that works in /api/user/profile
                profile = self.get_user_profile_by_email(employee.email)

                if profile:
                    profiles.append({
                        "id":     profile["id"],
                        "name":   profile["name"],
                        "skills": profile["skills"],   # ← same skills that /api/user/profile returns
                    })

            print(f"[DEBUG] Loaded {len(profiles)} profiles")
            for p in profiles:
                print(f"  → {p['name']}: {p['skills']}")

            return profiles
        finally:
            session.close()