"""Learning Path Agent using LangGraph - produces roadmap.sh-style personalized roadmaps."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, StateGraph

logger = logging.getLogger(__name__)

# ── Directory paths (same as standalone agent) ────────────────────────────────
ROOT         = Path(__file__).resolve().parents[2]
ROADMAPS_DIR = ROOT / "roadmaps_standard"
TOPICS_DIR   = ROOT / "topics_only"


def _roadmap_dirs() -> list[Path]:
    candidates = [
        ROOT / "roadmaps_standard",
        ROOT / "roadmap_agent" / "roadmaps_standard",
    ]
    return [path for path in candidates if path.exists()]


def _find_topics_file(roadmap_id: str) -> Path | None:
    candidates = [
        ROOT / "topics_only" / f"{roadmap_id}.json",
        ROOT / "roadmap_agent" / "topics_only" / f"{roadmap_id}.json",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None

# ══════════════════════════════════════════════════════════════════════════════
# AgentTrace  (mirrors standalone AgentTrace exactly)
# ══════════════════════════════════════════════════════════════════════════════
class AgentTrace:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.step = 0

    def add(self, event_type: str, message: str, **data: Any) -> None:
        self.step += 1
        self.events.append(
            {
                "step":      self.step,
                "type":      event_type,
                "message":   message,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                **data,
            }
        )

    def count(self, event_type: str) -> int:
        return sum(1 for e in self.events if e.get("type") == event_type)

    def summary(self) -> dict[str, Any]:
        return {
            "trace_file":   "roadmap_agent/agent_trace.json",
            "report_file":  "roadmap_agent/agent_report.md",
            "total_events": len(self.events),
            "observations": self.count("observe"),
            "decisions":    self.count("decision"),
            "tool_calls":   self.count("tool_call"),
            "validations":  self.count("validation"),
            "fallbacks":    self.count("fallback"),
        }

# ══════════════════════════════════════════════════════════════════════════════
# LangGraph state
# ══════════════════════════════════════════════════════════════════════════════
class LearningAgentState(TypedDict):
    skill_gap:        Dict[str, Any]
    skill_gaps:       List[str]
    current_skills:   List[str]
    target_role:      str
    learning_style:   str
    skill_entries:    List[Dict[str, Any]]
    trace:            Any
    phases:           List[Dict[str, Any]]
    edges:            List[Dict[str, Any]]
    source_roadmaps:  List[str]
    uncovered_skills: List[str]
    issues:           List[Dict[str, str]]
    messages:         List[BaseMessage]
    current_step:     str
    error:            Optional[str]
    # ── NEW: database storage results ─────────────────────────────────────────
    db_result:        Optional[Dict[str, Any]]

# ══════════════════════════════════════════════════════════════════════════════
# Database Storage Layer
# ══════════════════════════════════════════════════════════════════════════════
class RoadmapDatabaseStorage:
    """
    Handles all database persistence for generated roadmap data.
    Stores roadmap metadata, phases, nodes, and edges into the DB.
    """

    def __init__(self, db_session: Any) -> None:
        """
        Args:
            db_session: SQLAlchemy session or any DB session object.
                        Pass None to run in dry-run / log-only mode.
        """
        self.db = db_session

    # ── public entry point ────────────────────────────────────────────────────
    def store_roadmap(self, roadmap: dict[str, Any]) -> dict[str, Any]:
        """
        Persist the full generated roadmap to the database.

        Execution order (mirrors the JSON structure):
          1. Upsert roadmap header row
          2. Upsert every phase row
          3. Upsert every node row  (bulk)
          4. Upsert every edge row  (bulk)

        Returns a summary dict with counts and the roadmap_id.
        """
        if self.db is None:
            logger.warning(
                "[DB] No session provided — running in dry-run mode."
            )
            return self._dry_run_summary(roadmap)

        try:
            roadmap_id = self._upsert_roadmap(roadmap)
            phase_ids  = self._upsert_phases(roadmap_id, roadmap["phases"])
            node_count = self._upsert_nodes(roadmap_id, roadmap["phases"])
            edge_count = self._upsert_edges(roadmap_id, roadmap["edges"])

            self.db.commit()

            summary = {
                "status":      "stored",
                "roadmap_id":  roadmap_id,
                "phases":      len(phase_ids),
                "nodes":       node_count,
                "edges":       edge_count,
            }
            logger.info(
                "[DB] Stored roadmap %s — %d phases, %d nodes, %d edges",
                roadmap_id, len(phase_ids), node_count, edge_count,
            )
            return summary

        except Exception as exc:
            self.db.rollback()
            logger.error("[DB] Storage failed — rolled back: %s", exc)
            raise

    # ── roadmap header ────────────────────────────────────────────────────────
    def _upsert_roadmap(self, roadmap: dict[str, Any]) -> str:
        """Insert or update the roadmap header row."""
        meta      = roadmap.get("metadata", {})
        roadmap_id= roadmap["roadmap_id"]

        self.db.execute(
            """
            INSERT INTO roadmaps (
                roadmap_id, roadmap_title, version, generated_with,
                generated_at, employee_id, employee_name, current_role,
                target_role, experience_years, readiness_score,
                readiness_category, readiness_message,
                total_phases, total_nodes, total_edges,
                source_roadmaps, uncovered_skills,
                agent_trace_summary, raw_metadata
            ) VALUES (
                :roadmap_id, :roadmap_title, :version, :generated_with,
                :generated_at, :employee_id, :employee_name, :current_role,
                :target_role, :experience_years, :readiness_score,
                :readiness_category, :readiness_message,
                :total_phases, :total_nodes, :total_edges,
                :source_roadmaps, :uncovered_skills,
                :agent_trace_summary, :raw_metadata
            )
            ON CONFLICT (roadmap_id) DO UPDATE SET
                roadmap_title       = EXCLUDED.roadmap_title,
                generated_at        = EXCLUDED.generated_at,
                total_phases        = EXCLUDED.total_phases,
                total_nodes         = EXCLUDED.total_nodes,
                total_edges         = EXCLUDED.total_edges,
                source_roadmaps     = EXCLUDED.source_roadmaps,
                uncovered_skills    = EXCLUDED.uncovered_skills,
                agent_trace_summary = EXCLUDED.agent_trace_summary,
                raw_metadata        = EXCLUDED.raw_metadata
            """,
            {
                "roadmap_id":          roadmap_id,
                "roadmap_title":       roadmap.get("roadmap_title"),
                "version":             roadmap.get("version", "1.0.0"),
                "generated_with":      roadmap.get("generated_with"),
                "generated_at":        roadmap.get("generated_at"),
                "employee_id":         meta.get("employee_id"),
                "employee_name":       meta.get("name"),
                "current_role":        meta.get("current_role"),
                "target_role":         meta.get("target_role"),
                "experience_years":    meta.get("experience_years"),
                "readiness_score":     meta.get("readiness_score"),
                "readiness_category":  meta.get("readiness_category"),
                "readiness_message":   meta.get("readiness_message"),
                "total_phases":        meta.get("total_phases", 0),
                "total_nodes":         meta.get("total_nodes", 0),
                "total_edges":         meta.get("total_edges", 0),
                "source_roadmaps":     json.dumps(
                    meta.get("source_roadmaps", [])
                ),
                "uncovered_skills":    json.dumps(
                    meta.get("uncovered_skills", [])
                ),
                "agent_trace_summary": json.dumps(
                    meta.get("agent_trace_summary", {})
                ),
                "raw_metadata":        json.dumps(meta),
            },
        )
        return roadmap_id

    # ── phases ────────────────────────────────────────────────────────────────
    def _upsert_phases(
        self, roadmap_id: str, phases: list[dict[str, Any]]
    ) -> list[str]:
        """Insert or update every phase row. Returns list of phase_ids."""
        phase_ids: list[str] = []

        for phase in phases:
            phase_id = phase["phase_id"]
            self.db.execute(
                """
                INSERT INTO roadmap_phases (
                    phase_id, roadmap_id, phase_title,
                    phase_order, skill, source
                ) VALUES (
                    :phase_id, :roadmap_id, :phase_title,
                    :phase_order, :skill, :source
                )
                ON CONFLICT (phase_id) DO UPDATE SET
                    phase_title  = EXCLUDED.phase_title,
                    phase_order  = EXCLUDED.phase_order,
                    skill        = EXCLUDED.skill,
                    source       = EXCLUDED.source
                """,
                {
                    "phase_id":    phase_id,
                    "roadmap_id":  roadmap_id,
                    "phase_title": phase.get("phase_title", "Phase"),
                    "phase_order": phase.get("phase_order", 99),
                    "skill":       phase.get("skill", ""),
                    "source":      phase.get("source", "standard_roadmap"),
                },
            )
            phase_ids.append(phase_id)

        return phase_ids

    # ── nodes ─────────────────────────────────────────────────────────────────
    def _upsert_nodes(
        self, roadmap_id: str, phases: list[dict[str, Any]]
    ) -> int:
        """
        Bulk insert/update all nodes across all phases.
        Returns total node count stored.
        """
        node_count = 0

        for phase in phases:
            phase_id = phase["phase_id"]
            for node in phase.get("nodes", []):
                self.db.execute(
                    """
                    INSERT INTO roadmap_nodes (
                        node_id, roadmap_id, phase_id,
                        original_node_id, label, type,
                        category, importance, status,
                        skill_status, skill_priority, skill_importance,
                        matched_skill, source_roadmap,
                        depends_on, raw_node
                    ) VALUES (
                        :node_id, :roadmap_id, :phase_id,
                        :original_node_id, :label, :type,
                        :category, :importance, :status,
                        :skill_status, :skill_priority, :skill_importance,
                        :matched_skill, :source_roadmap,
                        :depends_on, :raw_node
                    )
                    ON CONFLICT (node_id) DO UPDATE SET
                        status           = EXCLUDED.status,
                        skill_status     = EXCLUDED.skill_status,
                        skill_priority   = EXCLUDED.skill_priority,
                        skill_importance = EXCLUDED.skill_importance,
                        matched_skill    = EXCLUDED.matched_skill,
                        depends_on       = EXCLUDED.depends_on,
                        raw_node         = EXCLUDED.raw_node
                    """,
                    {
                        "node_id":          node["node_id"],
                        "roadmap_id":       roadmap_id,
                        "phase_id":         phase_id,
                        "original_node_id": node.get("original_node_id"),
                        "label":            node.get("label"),
                        "type":             node.get("type"),
                        "category":         node.get("category"),
                        "importance":       node.get("importance"),
                        "status":           node.get("status", "locked"),
                        "skill_status":     node.get("skill_status"),
                        "skill_priority":   node.get("skill_priority"),
                        "skill_importance": node.get("skill_importance"),
                        "matched_skill":    node.get("matched_skill"),
                        "source_roadmap":   node.get("source_roadmap"),
                        "depends_on":       json.dumps(
                            node.get("depends_on", [])
                        ),
                        "raw_node":         json.dumps(node),
                    },
                )
                node_count += 1

        return node_count

    # ── edges ─────────────────────────────────────────────────────────────────
    def _upsert_edges(
        self, roadmap_id: str, edges: list[dict[str, Any]]
    ) -> int:
        """
        Bulk insert/update all edges.
        Returns total edge count stored.
        """
        for edge in edges:
            self.db.execute(
                """
                INSERT INTO roadmap_edges (
                    roadmap_id, source_node_id, target_node_id, edge_type
                ) VALUES (
                    :roadmap_id, :source, :target, :edge_type
                )
                ON CONFLICT (roadmap_id, source_node_id, target_node_id)
                DO UPDATE SET
                    edge_type = EXCLUDED.edge_type
                """,
                {
                    "roadmap_id": roadmap_id,
                    "source":     edge["source"],
                    "target":     edge["target"],
                    "edge_type":  edge.get("type", "optional"),
                },
            )
        return len(edges)

    # ── dry-run fallback ──────────────────────────────────────────────────────
    def _dry_run_summary(self, roadmap: dict[str, Any]) -> dict[str, Any]:
        """Log what would be stored without touching any DB."""
        total_nodes = sum(
            len(p.get("nodes", [])) for p in roadmap.get("phases", [])
        )
        summary = {
            "status":     "dry_run",
            "roadmap_id": roadmap.get("roadmap_id"),
            "phases":     len(roadmap.get("phases", [])),
            "nodes":      total_nodes,
            "edges":      len(roadmap.get("edges", [])),
        }
        logger.info("[DB-DRY-RUN] Would store: %s", summary)
        return summary

# ══════════════════════════════════════════════════════════════════════════════
# Pure helper functions  (unchanged — ported 1-to-1 from standalone agent)
# ══════════════════════════════════════════════════════════════════════════════
def _normalize_text(value: Any) -> str:
    text = str(value or "").lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def _split_tokens(value: Any) -> set[str]:
    return {t for t in _normalize_text(value).split() if t}

def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def _normalize_skill_entry(entry: dict[str, Any], bucket: str) -> dict[str, Any]:
    user_level     = _to_int(entry.get("user_level",     entry.get("currentLevel",  0)))
    required_level = _to_int(entry.get("required_level", entry.get("requiredLevel", 0)))
    gap = entry.get("gap")
    if gap is None:
        gap = max(0, required_level - user_level)
    return {
        "skill":          _normalize_text(entry.get("skill", entry.get("name", ""))),
        "user_level":     user_level,
        "required_level": required_level,
        "gap":            _to_int(gap),
        "priority":       entry.get("priority",   ""),
        "importance":     entry.get("importance", ""),
        "category":       entry.get("category",   ""),
        "status":         entry.get(
            "status", "in_progress" if bucket == "skill_gaps" else "locked"
        ),
        "bucket":         bucket,
    }

def _extract_skill_entries(skill_gap: dict[str, Any]) -> list[dict[str, Any]]:
    analysis = skill_gap.get("skill_analysis", {})
    buckets  = [
        ("skill_gaps",              analysis.get("skill_gaps",              [])),
        ("missing_core_skills",     analysis.get("missing_core_skills",     [])),
        ("missing_optional_skills", analysis.get("missing_optional_skills", [])),
    ]
    entries: list[dict[str, Any]] = []
    seen:    set[str]             = set()
    for bucket, items in buckets:
        for item in items:
            if not isinstance(item, dict):
                continue
            entry = _normalize_skill_entry(item, bucket)
            if entry["skill"] and entry["skill"] not in seen:
                seen.add(entry["skill"])
                entries.append(entry)
    return entries

def _roadmap_score(skill: str, roadmap_id: str, roadmap_data: dict[str, Any]) -> int:
    skill_tokens = _split_tokens(skill)
    if not skill_tokens:
        return 0
    searchable = [
        roadmap_id.replace("-", " "),
        roadmap_data.get("roadmap_title", ""),
    ]
    topics_path = _find_topics_file(roadmap_id)
    if topics_path is not None:
        topics = _load_json(topics_path).get("topics", [])
        searchable.extend(str(t) for t in topics)
    score = 0
    for item in searchable:
        item_tokens = _split_tokens(item)
        overlap     = len(skill_tokens.intersection(item_tokens))
        score       = max(score, overlap)
        if skill_tokens and skill_tokens.issubset(item_tokens):
            score = max(score, overlap + 2)
    id_tokens = _split_tokens(roadmap_id.replace("-", " "))
    if skill_tokens.issubset(id_tokens):
        score += 5
    return score

def _resolve_roadmap(skill: str) -> tuple[str | None, dict[str, Any] | None]:
    best: tuple[int, str | None, dict[str, Any] | None] = (0, None, None)
    directories = _roadmap_dirs()
    if not directories:
        return None, None
    for directory in directories:
        for path in directory.glob("*.json"):
            if path.name == "_conversion_summary.json":
                continue
            data = _load_json(path)
            score = _roadmap_score(skill, path.stem, data)
            if score > best[0]:
                best = (score, path.stem, data)
    return best[1], best[2]

def _extract_nodes(
    roadmap: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows:     list[dict[str, Any]]      = []
    node_map: dict[str, dict[str, Any]] = {}
    for phase in roadmap.get("phases", []):
        for node in phase.get("nodes", []):
            row                 = dict(node)
            row["_phase_id"]    = phase.get("phase_id")
            row["_phase_title"] = phase.get("phase_title")
            row["_phase_order"] = phase.get("phase_order", 99)
            rows.append(row)
            node_map[row["node_id"]] = row
    return rows, node_map

def _dependency_closure(
    selected: set[str], node_map: dict[str, dict[str, Any]]
) -> set[str]:
    result = set(selected)
    stack  = list(selected)
    while stack:
        node_id = stack.pop()
        node    = node_map.get(node_id)
        if not node:
            continue
        for dep in node.get("depends_on", []) or []:
            if dep in node_map and dep not in result:
                result.add(dep)
                stack.append(dep)
    return result

def _score_node(skill: str, node: dict[str, Any]) -> int:
    skill_tokens = _split_tokens(skill)
    text = " ".join(
        str(node.get(k, ""))
        for k in ("label", "skill_key", "category", "_phase_title")
    )
    node_tokens = _split_tokens(text)
    if not skill_tokens or not node_tokens:
        return 0
    score = len(skill_tokens.intersection(node_tokens))
    if _normalize_text(skill) in _normalize_text(text):
        score += 3
    if node.get("type") == "topic":
        score += 1
    if node.get("importance") == "core":
        score += 1
    return score

def _deterministic_select(
    entry:    dict[str, Any],
    rows:     list[dict[str, Any]],
    node_map: dict[str, dict[str, Any]],
) -> set[str]:
    skill          = entry["skill"]
    user_level     = _to_int(entry.get("user_level"))
    required_level = _to_int(entry.get("required_level"))
    gap = max(1, _to_int(entry.get("gap"), max(1, required_level - user_level)))
    scored = [(_score_node(skill, row), row) for row in rows]
    scored = [(s, row) for s, row in scored if s > 0]
    if not scored:
        scored = [
            (1, row)
            for row in rows
            if row.get("type") == "topic" and row.get("importance") == "core"
        ]
    if user_level > 0:
        limit = min(len(scored), max(6, gap * 8))
        scored.sort(
            key=lambda item: (
                -item[1].get("_phase_order", 0),
                -item[0],
                item[1].get("node_id", ""),
            )
        )
    else:
        limit = min(len(scored), max(10, gap * 5, required_level * 5))
        scored.sort(
            key=lambda item: (
                -item[0],
                item[1].get("_phase_order", 99),
                item[1].get("node_id", ""),
            )
        )
    return _dependency_closure(
        {row["node_id"] for _, row in scored[:limit]}, node_map
    )

def _resolve_llm_ids(raw_ids: list[Any], rows: list[dict[str, Any]]) -> list[str]:
    valid_ids    = {row["node_id"] for row in rows}
    label_to_id  = {_normalize_text(row.get("label")): row["node_id"] for row in rows}
    suffix_to_id = {row["node_id"].split("--", 1)[-1]: row["node_id"] for row in rows}
    resolved: list[str] = []
    for raw in raw_ids:
        if not isinstance(raw, str):
            continue
        value = raw.strip()
        key   = _normalize_text(value)
        if value in valid_ids:
            resolved.append(value)
        elif value in suffix_to_id:
            resolved.append(suffix_to_id[value])
        elif key in label_to_id:
            resolved.append(label_to_id[key])
    return list(dict.fromkeys(resolved))

def _llm_select_nodes(
    llm_client: Any,
    entry:      dict[str, Any],
    roadmap_id: str,
    rows:       list[dict[str, Any]],
) -> list[str]:
    if llm_client is None:
        return []
    compact_nodes = [
        {
            "node_id":    row["node_id"],
            "label":      row.get("label"),
            "type":       row.get("type"),
            "category":   row.get("category"),
            "importance": row.get("importance"),
            "phase_title":row.get("_phase_title"),
            "depends_on": row.get("depends_on", []),
        }
        for row in rows
    ]
    prompt = {
        "role":        "roadmap node selection agent",
        "instruction": (
            "The skill is from the skill_gaps category. Use the given roadmap "
            "as the source of truth and decide which node_ids should be present "
            "to close only this user's gap. Return JSON only."
        ),
        "skill_gap_entry": entry,
        "roadmap_id":      roadmap_id,
        "available_nodes": compact_nodes,
        "rules": [
            "Return only node ids from available_nodes.",
            "Prefer nodes at or above current level; skip basics already known.",
            "Keep the result focused on the gap, not the full roadmap.",
            "Include prerequisite node ids only when required for selected nodes.",
        ],
        "output_schema": {"selected_node_ids": ["node-id"]},
    }
    try:
        response = llm_client.chat.completions.create(
            model=getattr(llm_client, "default_model", "llama-3.3-70b-versatile"),
            temperature=0.1,
            messages=[
                {"role": "system",  "content": "You are a strict JSON roadmap selection agent."},
                {"role": "user",    "content": json.dumps(prompt, ensure_ascii=True)},
            ],
        )
        raw = response.choices[0].message.content or ""
    except Exception as exc:
        logger.warning("[LLM] Node selection call failed: %s", exc)
        return []
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if json_match:
        try:
            obj = json.loads(json_match.group())
            if isinstance(obj.get("selected_node_ids"), list):
                return _resolve_llm_ids(obj["selected_node_ids"], rows)
        except json.JSONDecodeError:
            pass
    list_match = re.search(r"\[.*\]", raw, re.DOTALL)
    if list_match:
        try:
            lst = json.loads(list_match.group())
            if isinstance(lst, list):
                return _resolve_llm_ids(lst, rows)
        except json.JSONDecodeError:
            pass
    return []

def _sort_nodes_topologically(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    node_map = {n["node_id"]: n for n in nodes}
    seen:   set[str]             = set()
    result: list[dict[str, Any]] = []
    def visit(node_id: str) -> None:
        if node_id in seen or node_id not in node_map:
            return
        seen.add(node_id)
        for dep in node_map[node_id].get("depends_on", []) or []:
            visit(dep)
        result.append(node_map[node_id])
    for node in nodes:
        visit(node["node_id"])
    return result

def _build_phases(
    roadmap:      dict[str, Any],
    roadmap_id:   str,
    entry:        dict[str, Any],
    selected_ids: set[str],
) -> list[dict[str, Any]]:
    phases:      list[dict[str, Any]] = []
    skill_status = entry.get("status", "locked")
    for phase in roadmap.get("phases", []):
        nodes: list[dict[str, Any]] = []
        for node in phase.get("nodes", []):
            if node.get("node_id") not in selected_ids:
                continue
            node_id  = node["node_id"]
            prefixed = {
                **node,
                "node_id":         f"{roadmap_id}--{node_id}",
                "depends_on":      [
                    f"{roadmap_id}--{dep}"
                    for dep in node.get("depends_on", [])
                    if dep in selected_ids
                ],
                "matched_skill":    entry["skill"],
                "source_roadmap":   roadmap_id,
                "original_node_id": node_id,
                "skill_status":     skill_status,
                "skill_priority":   entry.get("priority",   ""),
                "skill_importance": entry.get("importance", ""),
            }
            if skill_status == "in_progress" and not prefixed["depends_on"]:
                prefixed["status"] = "available"
            nodes.append(prefixed)
        if nodes:
            phases.append(
                {
                    "phase_id":    f"{roadmap_id}--{phase.get('phase_id')}",
                    "phase_title": phase.get("phase_title", "Phase"),
                    "phase_order": phase.get("phase_order", 99),
                    "skill":       entry["skill"],
                    "source":      "standard_roadmap",
                    "nodes":       _sort_nodes_topologically(nodes),
                }
            )
    return phases

def _build_edges(phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]]     = []
    seen:  set[tuple[str, str]]     = set()
    for phase in phases:
        for node in phase.get("nodes", []):
            target    = node["node_id"]
            edge_type = "required" if node.get("importance") == "core" else "optional"
            for source in node.get("depends_on", []) or []:
                if (source, target) in seen:
                    continue
                seen.add((source, target))
                edges.append({"source": source, "target": target, "type": edge_type})
    return edges


def _summarize_learning_path(
    all_gaps:    list[str],
    phases:      list[dict[str, Any]],
    target_role: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the flat ``learning_path`` summary and ``project_roadmap`` consumed
    by the API compatibility layer (``main._roadmap_compat_payload``) and the
    frontend, derived from the generated roadmap graph."""
    gaps = [g for g in all_gaps if g]

    # Sum estimated hours per matched skill from the generated nodes.
    hours_by_skill: dict[str, int] = {}
    for phase in phases:
        for node in phase.get("nodes", []):
            skill = node.get("matched_skill", "")
            if not skill:
                continue
            hours_by_skill[skill] = hours_by_skill.get(skill, 0) + _to_int(
                node.get("estimated_hours"), 0
            )

    def _weeks(skills: list[str]) -> int:
        total_hours = sum(hours_by_skill.get(s, 20) for s in skills)
        # ~10 study hours per week, with a two-week floor per skill.
        return max(len(skills) * 2, -(-total_hours // 10))

    # Split the gap skills across three progression phases.
    total = len(gaps)
    step  = max(1, -(-total // 3)) if total else 0  # ceil(total / 3)
    foundation_skills   = gaps[0:step]
    intermediate_skills = gaps[step:2 * step]
    advanced_skills     = gaps[2 * step:]

    phase_details = {
        "foundation": {
            "skills":         foundation_skills,
            "duration_weeks": _weeks(foundation_skills),
            "description":    "Establish the fundamentals for the core skill gaps.",
        },
        "intermediate": {
            "skills":         intermediate_skills,
            "duration_weeks": _weeks(intermediate_skills),
            "description":    "Apply the skills to realistic, hands-on workloads.",
        },
        "advanced": {
            "skills":         advanced_skills,
            "duration_weeks": _weeks(advanced_skills),
            "description":    "Master advanced topics and integrate them end-to-end.",
        },
    }

    learning_path = {
        "total_gaps":            total,
        "phases":                phase_details,
        "total_estimated_weeks": sum(p["duration_weeks"] for p in phase_details.values()),
    }

    project_roadmap = {
        "projects": [
            {
                "project":     f"{target_role}: {skill.title()} Capstone",
                "skill":       skill,
                "description": f"Build a hands-on project that demonstrates {skill}.",
            }
            for skill in gaps
        ]
    }
    return learning_path, project_roadmap


def _slugify_skill(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _normalize_text(value))
    slug = slug.strip("-")
    return slug or "skill"


def _build_fallback_phases(
    skill_entries: list[dict[str, Any]],
    target_role: str,
) -> list[dict[str, Any]]:
    """Build a minimal roadmap graph when source roadmap files are unavailable."""
    if not skill_entries:
        return []

    phase_template = [
        ("foundation", "Foundation Setup", 1),
        ("core", "Core Skill Development", 2),
        ("applied", "Applied Projects", 3),
    ]

    phases: list[dict[str, Any]] = [
        {
            "phase_id": f"fallback--{phase_id}",
            "phase_title": phase_title,
            "phase_order": phase_order,
            "skill": "multi-skill",
            "source": "fallback_roadmap",
            "nodes": [],
        }
        for phase_id, phase_title, phase_order in phase_template
    ]

    for entry in skill_entries:
        skill = entry.get("skill", "")
        if not skill:
            continue

        skill_slug = _slugify_skill(skill)
        importance = entry.get("importance", "core") or "core"
        priority = entry.get("priority", "high") or "high"
        skill_status = entry.get("status", "locked") or "locked"

        foundation_id = f"fallback--{skill_slug}--foundation"
        core_id = f"fallback--{skill_slug}--core"
        project_id = f"fallback--{skill_slug}--project"

        phases[0]["nodes"].append(
            {
                "node_id": foundation_id,
                "label": f"{skill.title()} Fundamentals",
                "type": "topic",
                "category": "foundation",
                "importance": importance,
                "difficulty": "beginner",
                "estimated_hours": 10,
                "depends_on": [],
                "resources": [{"type": "learning", "format": "guided"}],
                "matched_skill": skill,
                "source_roadmap": "fallback_roadmap",
                "original_node_id": f"{skill_slug}--foundation",
                "skill_status": skill_status,
                "skill_priority": priority,
                "skill_importance": importance,
                "status": "available" if skill_status == "in_progress" else "locked",
            }
        )

        phases[1]["nodes"].append(
            {
                "node_id": core_id,
                "label": f"Implement {skill.title()} in Real Workloads",
                "type": "topic",
                "category": "core",
                "importance": importance,
                "difficulty": "intermediate",
                "estimated_hours": 14,
                "depends_on": [foundation_id],
                "resources": [{"type": "practice", "format": "lab"}],
                "matched_skill": skill,
                "source_roadmap": "fallback_roadmap",
                "original_node_id": f"{skill_slug}--core",
                "skill_status": skill_status,
                "skill_priority": priority,
                "skill_importance": importance,
            }
        )

        phases[2]["nodes"].append(
            {
                "node_id": project_id,
                "label": f"{target_role}: {skill.title()} Capstone",
                "type": "project",
                "category": "applied",
                "importance": importance,
                "difficulty": "advanced",
                "estimated_hours": 18,
                "depends_on": [core_id],
                "resources": [{"type": "project", "format": "capstone"}],
                "matched_skill": skill,
                "source_roadmap": "fallback_roadmap",
                "original_node_id": f"{skill_slug}--project",
                "skill_status": skill_status,
                "skill_priority": priority,
                "skill_importance": importance,
            }
        )

    return [
        {
            **phase,
            "nodes": _sort_nodes_topologically(phase.get("nodes", [])),
        }
        for phase in phases
        if phase.get("nodes")
    ]

def _validate_roadmap(
    roadmap:       dict[str, Any],
    skill_entries: list[dict[str, Any]],
) -> list[dict[str, str]]:
    issues:   list[dict[str, str]] = []
    nodes    = [n for p in roadmap.get("phases", []) for n in p.get("nodes", [])]
    node_ids = {n.get("node_id") for n in nodes}
    matched  = {n.get("matched_skill") for n in nodes if n.get("matched_skill")}
    for entry in skill_entries:
        if entry["skill"] not in matched:
            issues.append({
                "severity": "critical",
                "code":     "missing_skill_coverage",
                "skill":    entry["skill"],
            })
    for node in nodes:
        for dep in node.get("depends_on", []) or []:
            if dep not in node_ids:
                issues.append({
                    "severity": "high",
                    "code":     "dangling_dependency",
                    "node":     node.get("node_id", ""),
                })
    for edge in roadmap.get("edges", []):
        if edge.get("source") not in node_ids or edge.get("target") not in node_ids:
            issues.append({
                "severity": "high",
                "code":     "dangling_edge",
                "edge":     json.dumps(edge),
            })
    return issues

# ══════════════════════════════════════════════════════════════════════════════
# LearningAgent  (LangGraph wrapper — input handling UNCHANGED)
# ══════════════════════════════════════════════════════════════════════════════
class LearningAgent:
    """
    LangGraph learning agent that generates roadmap.sh-style personalized
    roadmaps and persists them to a database.
    Input handling is identical to the original LangGraph file.
    """

    def __init__(
        self,
        llm_client:  Optional[Any] = None,
        db_session:  Optional[Any] = None,   # ← NEW: inject your DB session
        **_kwargs: Any,
    ):
        self.llm   = llm_client
        self.db    = RoadmapDatabaseStorage(db_session)   # ← storage layer
        self.graph = self._build_graph()

    # ── Graph wiring ──────────────────────────────────────────────────────────
    def _build_graph(self) -> Any:
        graph = StateGraph(LearningAgentState)

        graph.add_node("think_plan",            self._think_plan_node)
        graph.add_node("process_skills",        self._process_skills_node)
        graph.add_node("validate_and_finalize", self._validate_and_finalize_node)
        graph.add_node("store_to_database",     self._store_to_database_node)  # ← NEW

        graph.set_entry_point("think_plan")
        graph.add_edge("think_plan",            "process_skills")
        graph.add_edge("process_skills",        "validate_and_finalize")
        graph.add_edge("validate_and_finalize", "store_to_database")           # ← NEW
        graph.add_edge("store_to_database",     END)                           # ← NEW

        return graph.compile()

    # ── Node 1 : think & plan (UNCHANGED) ────────────────────────────────────
    def _think_plan_node(self, state: LearningAgentState) -> dict:
        trace: AgentTrace = state["trace"]
        trace.add(
            "observe",
            "Starting roadmap agent run (LangGraph)",
            target_role  = state["target_role"],
            skill_count  = len(state["skill_entries"]),
        )
        ordered = sorted(
            state["skill_entries"],
            key=lambda e: 0 if e["bucket"] == "skill_gaps" else 1,
        )
        trace.add(
            "decision",
            "Decided skill processing order",
            reason_code="skill_gaps_first_then_missing_skills",
            skill_order=[
                {"skill": e["skill"], "bucket": e["bucket"]} for e in ordered
            ],
        )
        logger.info(
            "[AGENT-THINK] Planning roadmap for %s (%d skills)",
            state["target_role"], len(ordered),
        )
        state["messages"].append(
            AIMessage(
                content=(
                    f"[THOUGHT] Generating roadmap for: {state['target_role']}\n"
                    f"Skills: {', '.join(e['skill'] for e in ordered[:10])}\n"
                    f"Strategy: resolve roadmap → LLM/deterministic select → "
                    f"dependency closure → build phases → edges"
                )
            )
        )
        state["skill_entries"] = ordered
        state["current_step"]  = "think"
        return state

    # ── Node 2 : process every skill (UNCHANGED) ──────────────────────────────
    def _process_skills_node(self, state: LearningAgentState) -> dict:
        trace:     AgentTrace          = state["trace"]
        phases:    list[dict[str,Any]] = []
        sources:   list[str]           = []
        uncovered: list[str]           = []

        for entry in state["skill_entries"]:
            skill = entry["skill"]
            roadmap_id, roadmap = _resolve_roadmap(skill)
            trace.add(
                "tool_call", "Resolved roadmap for skill",
                tool="resolve_roadmap",
                input={"skill": skill},
                output={"roadmap_id": roadmap_id, "found": bool(roadmap)},
            )
            if not roadmap_id or not roadmap:
                logger.info("[AGENT] %s: no roadmap found", skill)
                trace.add(
                    "decision", "Marked skill uncovered — no roadmap found",
                    skill=skill, reason_code="roadmap_not_found",
                )
                uncovered.append(skill)
                continue

            rows, node_map = _extract_nodes(roadmap)
            trace.add(
                "tool_call", "Extracted roadmap nodes",
                tool="extract_nodes",
                input={"roadmap_id": roadmap_id},
                output={"node_count": len(rows)},
            )

            if entry["bucket"] == "skill_gaps":
                logger.info("[AGENT] %s: skill_gaps → LLM selection from %s", skill, roadmap_id)
                trace.add(
                    "decision", "Skill is in skill_gaps — use LLM node selection",
                    skill=skill, roadmap_id=roadmap_id,
                    reason_code="skill_gap_requires_llm_selection",
                )
                selected = set(_llm_select_nodes(self.llm, entry, roadmap_id, rows))
                trace.add(
                    "tool_call", "LLM selected roadmap nodes",
                    tool="llm_select_nodes",
                    input={"skill": skill, "available_nodes": len(rows)},
                    output={"selected_nodes": len(selected)},
                )
                if not selected:
                    logger.info("[AGENT] %s: LLM empty → deterministic fallback", skill)
                    trace.add(
                        "fallback",
                        "LLM returned no usable nodes — using deterministic selector",
                        skill=skill, reason_code="llm_empty_or_unavailable",
                    )
                    selected = _deterministic_select(entry, rows, node_map)
                    trace.add(
                        "tool_call", "Selected nodes with deterministic fallback",
                        tool="deterministic_select",
                        input={"skill": skill},
                        output={"selected_nodes": len(selected)},
                    )
            else:
                logger.info(
                    "[AGENT] %s: %s → deterministic selection from %s",
                    skill, entry["bucket"], roadmap_id,
                )
                trace.add(
                    "decision",
                    "Skill is missing/optional — use focused deterministic selection",
                    skill=skill, roadmap_id=roadmap_id, bucket=entry["bucket"],
                    reason_code="missing_skill_uses_focused_selection",
                )
                selected = _deterministic_select(entry, rows, node_map)
                trace.add(
                    "tool_call", "Selected focused roadmap nodes",
                    tool="deterministic_select",
                    input={"skill": skill},
                    output={"selected_nodes": len(selected)},
                )

            before   = len(selected)
            selected = _dependency_closure(selected, node_map)
            trace.add(
                "tool_call", "Applied dependency closure",
                tool="dependency_closure",
                input={"skill": skill, "selected_before": before},
                output={"selected_after": len(selected)},
            )

            skill_phases = _build_phases(roadmap, roadmap_id, entry, selected)
            trace.add(
                "tool_call", "Built output phases for skill",
                tool="build_phases",
                input={"skill": skill, "selected_nodes": len(selected)},
                output={
                    "phase_count": len(skill_phases),
                    "node_count":  sum(len(p.get("nodes", [])) for p in skill_phases),
                },
            )

            if not skill_phases:
                trace.add(
                    "decision", "Marked skill uncovered — no phases produced",
                    skill=skill, reason_code="empty_phase_output",
                )
                uncovered.append(skill)
                continue

            phases.extend(skill_phases)
            if roadmap_id not in sources:
                sources.append(roadmap_id)

        if not phases and state["skill_entries"]:
            fallback_phases = _build_fallback_phases(
                state["skill_entries"],
                state["target_role"],
            )
            if fallback_phases:
                phases.extend(fallback_phases)
                if "fallback_roadmap" not in sources:
                    sources.append("fallback_roadmap")
                uncovered = []
                trace.add(
                    "fallback",
                    "Generated fallback roadmap graph from skill entries",
                    reason_code="no_standard_roadmap_sources",
                    phase_count=len(fallback_phases),
                    node_count=sum(len(p.get("nodes", [])) for p in fallback_phases),
                )

        state["phases"]          = phases
        state["source_roadmaps"] = sources
        state["uncovered_skills"]= uncovered
        total_nodes = sum(len(p.get("nodes", [])) for p in phases)
        state["messages"].append(
            AIMessage(
                content=(
                    f"[OBSERVE] Processed {len(state['skill_entries'])} skills\n"
                    f"  Phases: {len(phases)} | Nodes: {total_nodes}\n"
                    f"  Sources: {', '.join(sources) or 'none'}\n"
                    f"  Uncovered: {', '.join(uncovered) or 'none'}"
                )
            )
        )
        state["current_step"] = "process"
        return state

    # ── Node 3 : validate & finalise (UNCHANGED) ──────────────────────────────
    def _validate_and_finalize_node(self, state: LearningAgentState) -> dict:
        trace: AgentTrace = state["trace"]
        for idx, phase in enumerate(state["phases"], start=1):
            phase["phase_order"] = idx
        edges       = _build_edges(state["phases"])
        total_nodes = sum(len(p.get("nodes", [])) for p in state["phases"])
        tmp_roadmap = {"phases": state["phases"], "edges": edges}
        issues      = _validate_roadmap(tmp_roadmap, state["skill_entries"])
        trace.add(
            "validation", "Validated generated roadmap",
            tool="validate_roadmap",
            output={"issue_count": len(issues), "issues": issues},
        )
        state["edges"]        = edges
        state["issues"]       = issues
        state["current_step"] = "complete"
        state["messages"].append(
            AIMessage(
                content=(
                    "[SUMMARY] Roadmap finalized ✓\n"
                    f"  {total_nodes} nodes · {len(state['phases'])} phases · "
                    f"{len(edges)} edges\n"
                    f"  Sources: {', '.join(state['source_roadmaps']) or 'none'}\n"
                    f"  Issues: {len(issues)}"
                )
            )
        )
        return state

    # ── Node 4 : store to database (NEW) ──────────────────────────────────────
    def _store_to_database_node(self, state: LearningAgentState) -> dict:
        """
        NEW LangGraph node — persists the fully validated roadmap to the DB.
        Runs after validate_and_finalize so only clean data is stored.
        """
        trace: AgentTrace = state["trace"]

        # ── build the final roadmap dict (same shape as generate_learning_roadmap) 
        profile   = state["skill_gap"].get("user_profile",     {})
        readiness = state["skill_gap"].get("readiness_summary", {})
        total_nodes = sum(len(p.get("nodes", [])) for p in state["phases"])

        roadmap = {
            "roadmap_id":    f"roadmap-agent--{profile.get('employee_id', 'emp')}",
            "roadmap_title": (
                f"Roadmap Agent - {profile.get('name', 'Employee')} "
                f"-> {state['target_role']}"
            ),
            "version":        "1.0.0",
            "generated_with": "roadmap-agent",
            "generated_at":   datetime.utcnow().isoformat() + "Z",
            "metadata": {
                "employee_id":        profile.get("employee_id"),
                "name":               profile.get("name"),
                "current_role":       profile.get("current_role"),
                "target_role":        state["target_role"],
                "experience_years":   profile.get("experience_years"),
                "readiness_score":    readiness.get("readiness_score"),
                "readiness_category": readiness.get("readiness_category"),
                "readiness_message":  readiness.get("readiness_message"),
                "total_phases":       len(state["phases"]),
                "total_nodes":        total_nodes,
                "total_edges":        len(state["edges"]),
                "source_roadmaps":    state["source_roadmaps"],
                "uncovered_skills":   sorted(set(state["uncovered_skills"])),
                "agent_issues":       state["issues"],
                "agent_trace_summary":state["trace"].summary(),
            },
            "phases": state["phases"],
            "edges":  state["edges"],
        }

        # ── call the storage layer ────────────────────────────────────────────
        trace.add(
            "tool_call",
            "Storing roadmap to database",
            tool  = "RoadmapDatabaseStorage.store_roadmap",
            input = {
                "roadmap_id":  roadmap["roadmap_id"],
                "total_phases":len(state["phases"]),
                "total_nodes": total_nodes,
                "total_edges": len(state["edges"]),
            },
        )

        db_result = self.db.store_roadmap(roadmap)

        trace.add(
            "tool_call",
            "Database storage complete",
            tool   = "RoadmapDatabaseStorage.store_roadmap",
            output = db_result,
        )

        state["db_result"]    = db_result
        state["current_step"] = "stored"
        state["messages"].append(
            AIMessage(
                content=(
                    f"[DB] Roadmap stored ✓  "
                    f"status={db_result.get('status')}  "
                    f"phases={db_result.get('phases')}  "
                    f"nodes={db_result.get('nodes')}  "
                    f"edges={db_result.get('edges')}"
                )
            )
        )
        return state

    # ── Input normalisation (UNCHANGED) ───────────────────────────────────────
    def _normalize_input(
        self,
        skill_gap_or_gaps: Any,
        current_skills:    Optional[List[str]],
        target_role:       Optional[str],
        learning_style:    str,
    ) -> tuple:
        if isinstance(skill_gap_or_gaps, dict):
            skill_gap     = skill_gap_or_gaps
            profile       = skill_gap.get("user_profile", {})
            resolved_role = (
                target_role
                or profile.get("target_role")
                or profile.get("role")
                or "Software Developer"
            )
            analysis  = skill_gap.get("skill_analysis", {})
            core_gaps = [
                str(g).strip().lower()
                for g in skill_gap.get("core_gaps", [])
                if str(g).strip()
            ]

            # Backward-compatible fallback: when only core_gaps are provided,
            # synthesize missing_core_skills so downstream node selection can run.
            has_bucket_entries = any(
                bool(analysis.get(bucket, []))
                for bucket in ("skill_gaps", "missing_core_skills", "missing_optional_skills")
            )
            if core_gaps and not has_bucket_entries:
                synthesized_missing = [
                    {
                        "skill": g,
                        "priority": "critical",
                        "importance": "core",
                        "user_level": 0,
                        "required_level": 4,
                        "gap": 4,
                        "status": "locked",
                        "category": "general",
                    }
                    for g in core_gaps
                ]
                analysis = {
                    **analysis,
                    "skill_gaps": analysis.get("skill_gaps", []),
                    "missing_core_skills": synthesized_missing,
                    "missing_optional_skills": analysis.get("missing_optional_skills", []),
                    "matched_skills": analysis.get("matched_skills", current_skills or []),
                }
                skill_gap = {**skill_gap, "skill_analysis": analysis}

            partial   = [
                i.get("skill", "")
                for i in analysis.get("skill_gaps", [])
                if i.get("skill")
            ]
            missing   = [
                i.get("skill", "")
                for i in analysis.get("missing_core_skills", [])
                if i.get("skill")
            ]
            all_gaps  = list(dict.fromkeys(core_gaps + partial + missing))
            inferred  = current_skills or analysis.get("matched_skills", []) or []
            return resolved_role, all_gaps, inferred, skill_gap
        else:
            gaps  = [
                str(g).strip().lower()
                for g in (skill_gap_or_gaps or [])
                if str(g).strip()
            ]
            role  = target_role or "Software Developer"
            skills= [
                str(s).strip().lower()
                for s in (current_skills or [])
                if str(s).strip()
            ]
            skill_gap = {
                "user_profile":  {"target_role": role},
                "skill_analysis": {
                    "skill_gaps": [],
                    "missing_core_skills": [
                        {
                            "skill":          g,
                            "priority":       "critical",
                            "importance":     "core",
                            "user_level":     0,
                            "required_level": 4,
                            "gap":            4,
                            "status":         "locked",
                            "category":       "general",
                        }
                        for g in gaps
                    ],
                    "missing_optional_skills": [],
                    "matched_skills": skills,
                },
                "core_gaps": gaps,
            }
            return role, gaps, skills, skill_gap

    # ── Public entry point (UNCHANGED) ────────────────────────────────────────
    def generate_learning_roadmap(
        self,
        skill_gap_or_gaps: Any,
        current_skills:    Optional[List[str]] = None,
        target_role:       Optional[str]       = None,
        learning_style:    str                 = "balanced",
    ) -> dict:
        resolved_role, all_gaps, inferred_skills, skill_gap = (
            self._normalize_input(
                skill_gap_or_gaps, current_skills, target_role, learning_style
            )
        )

        skill_entries = _extract_skill_entries(skill_gap)
        trace         = AgentTrace()

        initial_state = LearningAgentState(
            skill_gap        = skill_gap,
            skill_gaps       = all_gaps,
            current_skills   = inferred_skills,
            target_role      = resolved_role,
            learning_style   = learning_style,
            skill_entries    = skill_entries,
            trace            = trace,
            phases           = [],
            edges            = [],
            source_roadmaps  = [],
            uncovered_skills = [],
            issues           = [],
            messages         = [
                HumanMessage(content=f"Generate roadmap for: {resolved_role}")
            ],
            current_step     = "",
            error            = None,
            db_result        = None,   # ← NEW field initialised
        )

        logger.info(
            "[AGENT] Starting roadmap generation for %s (%d gaps)",
            resolved_role, len(all_gaps),
        )

        result = self.graph.invoke(initial_state)

        # ── assemble final return payload ─────────────────────────────────────
        profile   = skill_gap.get("user_profile",     {})
        readiness = skill_gap.get("readiness_summary", {})

        for idx, phase in enumerate(result["phases"], start=1):
            phase["phase_order"] = idx

        edges       = result["edges"]
        total_nodes = sum(len(p.get("nodes", [])) for p in result["phases"])

        learning_path, project_roadmap = _summarize_learning_path(
            all_gaps, result["phases"], resolved_role
        )

        roadmap = {
            "roadmap_id":    f"roadmap-agent--{profile.get('employee_id', 'emp')}",
            "roadmap_title": (
                f"Roadmap Agent - {profile.get('name', 'Employee')} "
                f"-> {resolved_role}"
            ),
            "version":        "1.0.0",
            "generated_with": "roadmap-agent",
            "generated_at":   datetime.utcnow().isoformat() + "Z",
            "metadata": {
                "employee_id":         profile.get("employee_id"),
                "name":                profile.get("name"),
                "current_role":        profile.get("current_role"),
                "target_role":         resolved_role,
                "experience_years":    profile.get("experience_years"),
                "readiness_score":     readiness.get("readiness_score"),
                "readiness_category":  readiness.get("readiness_category"),
                "readiness_message":   readiness.get("readiness_message"),
                "total_phases":        len(result["phases"]),
                "total_nodes":         total_nodes,
                "total_edges":         len(edges),
                "source_roadmaps":     result["source_roadmaps"],
                "uncovered_skills":    sorted(set(result["uncovered_skills"])),
                "agent_issues":        result["issues"],
                "agent_trace_summary": trace.summary(),
            },
            "phases": result["phases"],
            "edges":  edges,
            # Flat summaries consumed by the API compat layer and the frontend.
            "skill_gaps":      all_gaps,
            "learning_path":   learning_path,
            "project_roadmap": project_roadmap,
            # ── NEW: surface DB result to caller ─────────────────────────────
            "db_result": result.get("db_result"),
        }

        return roadmap