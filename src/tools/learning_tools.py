"""Learning tools powered by roadmap.sh-style structured roadmaps."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROADMAPS_DIR = _PROJECT_ROOT / "roadmap_agent" / "roadmaps_standard"
TOPICS_DIR = _PROJECT_ROOT / "roadmap_agent" / "topics_only"


class LearningTools:
    """Roadmap.sh-style learning tools used by the LearningAgent."""

    def __init__(self, esco_repo=None, llm_client=None):
        self.esco_repo = esco_repo
        self.llm_client = llm_client

    # ── Text helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def normalize_text(value: Any) -> str:
        text = str(value or "").lower().strip()
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def split_tokens(value: Any) -> Set[str]:
        return {t for t in LearningTools.normalize_text(value).split() if t}

    # ── Roadmap resolution ────────────────────────────────────────────────────

    def _roadmap_score(self, skill: str, roadmap_id: str, roadmap_data: Dict[str, Any]) -> int:
        skill_tokens = self.split_tokens(skill)
        if not skill_tokens:
            return 0

        searchable = [roadmap_id.replace("-", " "), roadmap_data.get("roadmap_title", "")]
        topics_path = TOPICS_DIR / f"{roadmap_id}.json"
        if topics_path.exists():
            try:
                topics = json.loads(topics_path.read_text(encoding="utf-8")).get("topics", [])
                searchable.extend(str(t) for t in topics)
            except Exception:
                pass

        score = 0
        for item in searchable:
            item_tokens = self.split_tokens(item)
            overlap = len(skill_tokens & item_tokens)
            score = max(score, overlap)
            if skill_tokens and skill_tokens.issubset(item_tokens):
                score = max(score, overlap + 2)

        id_tokens = self.split_tokens(roadmap_id.replace("-", " "))
        if skill_tokens.issubset(id_tokens):
            score += 5
        return score

    def resolve_roadmap(self, skill: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Find the best-matching roadmap.sh roadmap for a given skill."""
        if not ROADMAPS_DIR.exists():
            logger.warning("[LearningTools] roadmaps_standard not found at %s", ROADMAPS_DIR)
            return None, None

        best: Tuple[int, Optional[str], Optional[Dict[str, Any]]] = (0, None, None)
        for path in ROADMAPS_DIR.glob("*.json"):
            if path.name == "_conversion_summary.json":
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                s = self._roadmap_score(skill, path.stem, data)
                if s > best[0]:
                    best = (s, path.stem, data)
            except Exception as exc:
                logger.debug("Score failed for %s: %s", path.stem, exc)

        return best[1], best[2]

    # ── Node helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def extract_nodes(roadmap: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        rows: List[Dict[str, Any]] = []
        node_map: Dict[str, Dict[str, Any]] = {}
        for phase in roadmap.get("phases", []):
            for node in phase.get("nodes", []):
                row = dict(node)
                row["_phase_id"] = phase.get("phase_id")
                row["_phase_title"] = phase.get("phase_title")
                row["_phase_order"] = phase.get("phase_order", 99)
                rows.append(row)
                node_map[row["node_id"]] = row
        return rows, node_map

    def _score_node(self, skill: str, node: Dict[str, Any]) -> int:
        skill_tokens = self.split_tokens(skill)
        text = " ".join(str(node.get(k, "")) for k in ("label", "skill_key", "category", "_phase_title"))
        node_tokens = self.split_tokens(text)
        if not skill_tokens or not node_tokens:
            return 0
        score = len(skill_tokens & node_tokens)
        if self.normalize_text(skill) in self.normalize_text(text):
            score += 3
        if node.get("type") == "topic":
            score += 1
        if node.get("importance") == "core":
            score += 1
        return score

    def dependency_closure(self, selected: Set[str], node_map: Dict[str, Dict[str, Any]]) -> Set[str]:
        result = set(selected)
        stack = list(selected)
        while stack:
            node_id = stack.pop()
            node = node_map.get(node_id)
            if not node:
                continue
            for dep in node.get("depends_on", []) or []:
                if dep in node_map and dep not in result:
                    result.add(dep)
                    stack.append(dep)
        return result

    def deterministic_select(
        self,
        entry: Dict[str, Any],
        rows: List[Dict[str, Any]],
        node_map: Dict[str, Dict[str, Any]],
    ) -> Set[str]:
        skill = entry.get("skill", "")
        user_level = int(entry.get("user_level", 0) or 0)
        required_level = int(entry.get("required_level", 0) or 0)
        gap = max(1, int(entry.get("gap", max(1, required_level - user_level)) or 1))

        scored = [(self._score_node(skill, row), row) for row in rows]
        scored = [(s, row) for s, row in scored if s > 0]
        if not scored:
            scored = [(1, row) for row in rows if row.get("type") == "topic" and row.get("importance") == "core"]

        if user_level > 0:
            limit = min(len(scored), max(6, gap * 8))
            scored.sort(key=lambda item: (-item[1].get("_phase_order", 0), -item[0], item[1].get("node_id", "")))
        else:
            limit = min(len(scored), max(10, gap * 5, required_level * 5))
            scored.sort(key=lambda item: (-item[0], item[1].get("_phase_order", 99), item[1].get("node_id", "")))

        return self.dependency_closure({row["node_id"] for _, row in scored[:limit]}, node_map)

    # ── LLM-guided node selection ─────────────────────────────────────────────

    def llm_select_nodes(
        self,
        entry: Dict[str, Any],
        roadmap_id: str,
        rows: List[Dict[str, Any]],
    ) -> List[str]:
        """Use LLM to pick gap-targeted nodes when a client is available."""
        if not self.llm_client:
            return []
        try:
            compact = [
                {
                    "node_id": row["node_id"],
                    "label": row.get("label"),
                    "type": row.get("type"),
                    "category": row.get("category"),
                    "importance": row.get("importance"),
                    "phase_title": row.get("_phase_title"),
                    "depends_on": row.get("depends_on", []),
                }
                for row in rows[:80]
            ]
            prompt = (
                "You are a strict JSON roadmap selection agent.\n"
                f"Skill gap entry: {json.dumps(entry)}\n"
                f"Roadmap: {roadmap_id}\n"
                "Select node_ids that close only this user's gap. "
                'Return ONLY: {"selected_node_ids": ["node-id", ...]}\n'
                f"Available nodes:\n{json.dumps(compact)}"
            )
            response = self.llm_client.invoke(prompt)
            content = getattr(response, "content", str(response)) or ""
            if not content:
                return []

            match = re.search(r'\{[^{}]*"selected_node_ids"[^{}]*\}', content, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                ids = parsed.get("selected_node_ids", [])
                valid = {row["node_id"] for row in rows}
                return [str(i).strip() for i in ids if str(i).strip() in valid]
        except Exception as exc:
            logger.debug("LLM node selection failed: %s", exc)
        return []

    # ── Phase and edge builders ───────────────────────────────────────────────

    def build_phases(
        self,
        roadmap: Dict[str, Any],
        roadmap_id: str,
        entry: Dict[str, Any],
        selected_ids: Set[str],
    ) -> List[Dict[str, Any]]:
        phases: List[Dict[str, Any]] = []
        skill_status = entry.get("status", "locked")
        for phase in roadmap.get("phases", []):
            nodes: List[Dict[str, Any]] = []
            for node in phase.get("nodes", []):
                if node.get("node_id") not in selected_ids:
                    continue
                node_id = node["node_id"]
                enriched = {
                    **node,
                    "node_id": f"{roadmap_id}--{node_id}",
                    "depends_on": [
                        f"{roadmap_id}--{dep}"
                        for dep in node.get("depends_on", [])
                        if dep in selected_ids
                    ],
                    "matched_skill": entry["skill"],
                    "source_roadmap": roadmap_id,
                    "original_node_id": node_id,
                    "skill_status": skill_status,
                    "skill_priority": entry.get("priority", ""),
                    "skill_importance": entry.get("importance", ""),
                }
                if skill_status == "in_progress" and not enriched["depends_on"]:
                    enriched["status"] = "available"
                nodes.append(enriched)
            if nodes:
                phases.append(
                    {
                        "phase_id": f"{roadmap_id}--{phase.get('phase_id')}",
                        "phase_title": phase.get("phase_title", "Phase"),
                        "phase_order": phase.get("phase_order", 99),
                        "skill": entry["skill"],
                        "source": "standard_roadmap",
                        "nodes": self._sort_topologically(nodes),
                    }
                )
        return phases

    def _sort_topologically(self, nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        node_map = {n["node_id"]: n for n in nodes}
        seen: Set[str] = set()
        result: List[Dict[str, Any]] = []

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

    def build_edges(self, phases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        edges: List[Dict[str, Any]] = []
        seen: Set[tuple] = set()
        for phase in phases:
            for node in phase.get("nodes", []):
                target = node["node_id"]
                for source in node.get("depends_on", []) or []:
                    if (source, target) in seen:
                        continue
                    seen.add((source, target))
                    edges.append(
                        {
                            "source": source,
                            "target": target,
                            "type": "required" if node.get("importance") == "core" else "optional",
                        }
                    )
        return edges

    # ── Core: skill-gap → roadmap.sh phases ──────────────────────────────────

    def process_skill_gap_to_roadmap(self, skill_gap: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a skill-gap analysis into roadmap.sh-style phases and edges."""
        skill_entries = self._extract_skill_entries(skill_gap)
        if not skill_entries:
            return {
                "phases": [],
                "edges": [],
                "source_roadmaps": [],
                "uncovered_skills": [],
                "issues": [],
                "trace": [],
            }

        all_phases: List[Dict[str, Any]] = []
        source_roadmaps: List[str] = []
        uncovered_skills: List[str] = []
        trace: List[Dict[str, Any]] = []

        ordered = sorted(skill_entries, key=lambda e: 0 if e.get("bucket") == "skill_gaps" else 1)

        for entry in ordered:
            skill = entry["skill"]
            roadmap_id, roadmap = self.resolve_roadmap(skill)
            trace.append({"action": "resolve_roadmap", "skill": skill, "roadmap_id": roadmap_id, "found": bool(roadmap)})

            if not roadmap_id or not roadmap:
                uncovered_skills.append(skill)
                trace.append({"action": "uncovered", "skill": skill, "reason": "no_roadmap_found"})
                logger.info("[LearningTools] No roadmap found for: %s", skill)
                continue

            rows, node_map = self.extract_nodes(roadmap)

            if entry.get("bucket") == "skill_gaps" and self.llm_client:
                selected_list = self.llm_select_nodes(entry, roadmap_id, rows)
                selected: Set[str] = set(selected_list)
                trace.append({"action": "llm_select", "skill": skill, "selected": len(selected)})
                if not selected:
                    selected = self.deterministic_select(entry, rows, node_map)
                    trace.append({"action": "deterministic_fallback", "skill": skill, "selected": len(selected)})
            else:
                selected = self.deterministic_select(entry, rows, node_map)
                trace.append({"action": "deterministic_select", "skill": skill, "selected": len(selected)})

            selected = self.dependency_closure(selected, node_map)
            phases = self.build_phases(roadmap, roadmap_id, entry, selected)

            if not phases:
                uncovered_skills.append(skill)
                continue

            all_phases.extend(phases)
            if roadmap_id not in source_roadmaps:
                source_roadmaps.append(roadmap_id)
            logger.info("[LearningTools] %s → %s (%d nodes)", skill, roadmap_id, sum(len(p["nodes"]) for p in phases))

        for i, phase in enumerate(all_phases, start=1):
            phase["phase_order"] = i

        edges = self.build_edges(all_phases)
        issues = self._validate_roadmap(all_phases, edges, skill_entries)

        return {
            "phases": all_phases,
            "edges": edges,
            "source_roadmaps": source_roadmaps,
            "uncovered_skills": sorted(set(uncovered_skills)),
            "issues": issues,
            "trace": trace,
        }

    # ── Skill entry extraction ────────────────────────────────────────────────

    def _extract_skill_entries(self, skill_gap: Dict[str, Any]) -> List[Dict[str, Any]]:
        analysis = skill_gap.get("skill_analysis", {})
        buckets = [
            ("skill_gaps", analysis.get("skill_gaps", [])),
            ("missing_core_skills", analysis.get("missing_core_skills", [])),
            ("missing_optional_skills", analysis.get("missing_optional_skills", [])),
        ]
        entries: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for bucket, items in buckets:
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                skill = self.normalize_text(item.get("skill", item.get("name", "")))
                if not skill or skill in seen:
                    continue
                seen.add(skill)
                entries.append(
                    {
                        "skill": skill,
                        "user_level": int(item.get("user_level", 0) or 0),
                        "required_level": int(item.get("required_level", 0) or 0),
                        "gap": int(item.get("gap", 0) or 0),
                        "priority": item.get("priority", ""),
                        "importance": item.get("importance", ""),
                        "category": item.get("category", ""),
                        "status": item.get("status", "locked"),
                        "bucket": bucket,
                    }
                )
        return entries

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate_roadmap(
        self,
        phases: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        skill_entries: List[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        issues: List[Dict[str, str]] = []
        nodes = [n for p in phases for n in p.get("nodes", [])]
        node_ids = {n.get("node_id") for n in nodes}
        matched = {n.get("matched_skill") for n in nodes if n.get("matched_skill")}

        for entry in skill_entries:
            if entry["skill"] not in matched:
                issues.append({"severity": "critical", "code": "missing_skill_coverage", "skill": entry["skill"]})
        for node in nodes:
            for dep in node.get("depends_on", []) or []:
                if dep not in node_ids:
                    issues.append({"severity": "high", "code": "dangling_dependency", "node": node.get("node_id", "")})
        for edge in edges:
            if edge.get("source") not in node_ids or edge.get("target") not in node_ids:
                issues.append({"severity": "high", "code": "dangling_edge", "edge": json.dumps(edge)})

        return issues

    # ── Backward-compatible helpers ───────────────────────────────────────────

    def generate_learning_path(
        self,
        skill_gaps: List[str],
        current_skills: List[str],
        learning_style: str = "balanced",
    ) -> Dict[str, Any]:
        if not skill_gaps:
            return {"total_gaps": 0, "phases": {}, "total_estimated_weeks": 0}
        n = len(skill_gaps)
        f = max(1, n // 3)
        m = max(1, n // 3)
        a = max(1, n - 2 * (n // 3))
        return {
            "total_gaps": n,
            "learning_style": learning_style,
            "phases": {
                "foundation": {"skills": skill_gaps[:f], "duration_weeks": 4 * f, "description": "Learn fundamentals and prerequisites"},
                "intermediate": {"skills": skill_gaps[f: f + m], "duration_weeks": 3 * m, "description": "Build practical projects"},
                "advanced": {"skills": skill_gaps[f + m:], "duration_weeks": 2 * a, "description": "Master and specialize"},
            },
            "total_estimated_weeks": 4 * f + 3 * m + 2 * a,
        }

    def create_project_based_roadmap(self, skill_gaps: List[str], target_role: str) -> Dict[str, Any]:
        return {
            "target_role": target_role,
            "projects": [{"project": f"Apply {s}", "skills": [s], "duration_weeks": 2, "difficulty": "Intermediate"} for s in skill_gaps[:5]],
            "total_projects": min(len(skill_gaps), 5),
            "total_duration_weeks": 2 * min(len(skill_gaps), 5),
            "methodology": "roadmap.sh-style structured learning",
        }

    def suggest_learning_resources(self, skills: List[str], learning_style: str = "balanced") -> Dict[str, Any]:
        resource_map = {
            "coursera": ["python", "data science", "machine learning", "aws", "cloud"],
            "udemy": ["web development", "react", "node", "docker", "javascript"],
            "pluralsight": ["java", "spring", "c#", "devops"],
            "freecodecamp": ["javascript", "react", "python", "html"],
            "official_docs": ["kubernetes", "docker", "aws", "spring", "tensorflow"],
        }
        resources: Dict[str, List[str]] = {}
        for skill in skills[:8]:
            for platform, mapped in resource_map.items():
                if any(s in skill.lower() for s in mapped):
                    resources.setdefault(platform, []).append(skill)
        return {
            "skills": skills,
            "learning_style": learning_style,
            "recommended_resources": resources or {"roadmap.sh": skills},
            "resource_count": len(resources),
        }
