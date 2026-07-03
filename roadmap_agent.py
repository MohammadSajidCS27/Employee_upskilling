from __future__ import annotations
import argparse
import json
import os
import re
import sys
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
import httpx
import urllib3
from groq import Groq


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.json_parser import safe_parse_json
from roadmap_agent.resource_allocation_agent import AgentTrace as RAAgentTrace, run_agent as run_resource_agent

warnings.filterwarnings("ignore", message="Unverified HTTPS request")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


ROADMAPS_DIR = ROOT / "roadmaps_standard"
TOPICS_DIR = ROOT / "topics_only"
DEFAULT_SKILL_GAP = ROOT / "skill_gap.json"
DEFAULT_OUTPUT = ROOT / "generated-roadmap.json"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
TRACE_OUTPUT = ROOT / "roadmap_agent" / "agent_trace.json"
REPORT_OUTPUT = ROOT / "roadmap_agent" / "agent_report.md"


@dataclass
class AgentState:
    skill_gap: dict[str, Any]
    model: str
    phases: list[dict[str, Any]] = field(default_factory=list)
    source_roadmaps: list[str] = field(default_factory=list)
    uncovered_skills: list[str] = field(default_factory=list)
    issues: list[dict[str, str]] = field(default_factory=list)
    trace_summary: dict[str, Any] = field(default_factory=dict)


class AgentTrace:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.step = 0

    def add(self, event_type: str, message: str, **data: Any) -> None:
        self.step += 1
        self.events.append(
            {
                "step": self.step,
                "type": event_type,
                "message": message,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                **data,
            }
        )

    def count(self, event_type: str) -> int:
        return sum(1 for event in self.events if event.get("type") == event_type)

    def summary(self) -> dict[str, Any]:
        return {
            "trace_file": "roadmap_agent/agent_trace.json",
            "report_file": "roadmap_agent/agent_report.md",
            "total_events": len(self.events),
            "observations": self.count("observe"),
            "decisions": self.count("decision"),
            "tool_calls": self.count("tool_call"),
            "validations": self.count("validation"),
            "fallbacks": self.count("fallback"),
        }

    def save(self, path: Path) -> None:
        save_json(path, {"events": self.events, "summary": self.summary()})


def load_local_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def make_client() -> Groq | None:
    load_local_env()
    api_key = os.getenv("GROQ_API_KEY") or os.getenv("LLM_GROQ_KEY")
    if not api_key:
        return None
    return Groq(
                api_key=api_key, 
                http_client=httpx.Client(verify=False)
                )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def save_agent_report(path: Path, trace: AgentTrace, roadmap: dict[str, Any]) -> None:
    metadata = roadmap.get("metadata", {})
    events = trace.events

    def table_rows(event_type: str) -> list[str]:
        rows = []
        for event in events:
            if event.get("type") != event_type:
                continue
            rows.append(
                "| {step} | {message} | {detail} |".format(
                    step=event.get("step"),
                    message=str(event.get("message", "")).replace("|", "\\|"),
                    detail=json.dumps(
                        {
                            key: value
                            for key, value in event.items()
                            if key not in {"step", "type", "message", "timestamp"}
                        },
                        ensure_ascii=False,
                    ).replace("|", "\\|"),
                )
            )
        return rows or ["| - | None | - |"]

    lines = [
        "# Roadmap Agent Run",
        "",
        "## Summary",
        f"- Generated with: `{roadmap.get('generated_with')}`",
        f"- Title: {roadmap.get('roadmap_title')}",
        f"- Total nodes: {metadata.get('total_nodes')}",
        f"- Total edges: {metadata.get('total_edges')}",
        f"- Source roadmaps: {', '.join(metadata.get('source_roadmaps', []))}",
        f"- Uncovered skills: {', '.join(metadata.get('uncovered_skills', [])) or 'none'}",
        f"- Agent issues: {len(metadata.get('agent_issues', []))}",
        "",
        "## Trace Summary",
        "```json",
        json.dumps(trace.summary(), indent=2),
        "```",
        "",
        "## Observations",
        "| Step | Message | Detail |",
        "|---:|---|---|",
        *table_rows("observe"),
        "",
        "## Decisions",
        "| Step | Message | Detail |",
        "|---:|---|---|",
        *table_rows("decision"),
        "",
        "## Tool Calls",
        "| Step | Message | Detail |",
        "|---:|---|---|",
        *table_rows("tool_call"),
        "",
        "## Fallbacks",
        "| Step | Message | Detail |",
        "|---:|---|---|",
        *table_rows("fallback"),
        "",
        "## Validation",
        "| Step | Message | Detail |",
        "|---:|---|---|",
        *table_rows("validation"),
        "",
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def normalize_text(value: Any) -> str:
    text = str(value or "").lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def split_tokens(value: Any) -> set[str]:
    return {token for token in normalize_text(value).split() if token}


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_skill_entry(entry: dict[str, Any], bucket: str) -> dict[str, Any]:
    user_level = to_int(entry.get("user_level", entry.get("currentLevel", 0)))
    required_level = to_int(entry.get("required_level", entry.get("requiredLevel", 0)))
    gap = entry.get("gap")
    if gap is None:
        gap = max(0, required_level - user_level)
    return {
        "skill": normalize_text(entry.get("skill", entry.get("name", ""))),
        "user_level": user_level,
        "required_level": required_level,
        "gap": to_int(gap),
        "priority": entry.get("priority", ""),
        "importance": entry.get("importance", ""),
        "category": entry.get("category", ""),
        "status": entry.get("status", "in_progress" if bucket == "skill_gaps" else "locked"),
        "bucket": bucket,
    }


def extract_skill_entries(skill_gap: dict[str, Any]) -> list[dict[str, Any]]:
    analysis = skill_gap.get("skill_analysis", {})
    buckets = [
        ("skill_gaps", analysis.get("skill_gaps", [])),
        ("missing_core_skills", analysis.get("missing_core_skills", [])),
        ("missing_optional_skills", analysis.get("missing_optional_skills", [])),
    ]

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bucket, items in buckets:
        for item in items:
            if not isinstance(item, dict):
                continue
            entry = normalize_skill_entry(item, bucket)
            if entry["skill"] and entry["skill"] not in seen:
                seen.add(entry["skill"])
                entries.append(entry)
    return entries


def roadmap_score(skill: str, roadmap_id: str, roadmap_data: dict[str, Any]) -> int:
    skill_tokens = split_tokens(skill)
    if not skill_tokens:
        return 0

    searchable = [roadmap_id.replace("-", " "), roadmap_data.get("roadmap_title", "")]
    topics_path = TOPICS_DIR / f"{roadmap_id}.json"
    if topics_path.exists():
        topics = load_json(topics_path).get("topics", [])
        searchable.extend(str(topic) for topic in topics)

    score = 0
    for item in searchable:
        item_tokens = split_tokens(item)
        overlap = len(skill_tokens.intersection(item_tokens))
        score = max(score, overlap)
        if skill_tokens and skill_tokens.issubset(item_tokens):
            score = max(score, overlap + 2)

    id_tokens = split_tokens(roadmap_id.replace("-", " "))
    if skill_tokens.issubset(id_tokens):
        score += 5
    return score


def resolve_roadmap(skill: str) -> tuple[str | None, dict[str, Any] | None]:
    best: tuple[int, str | None, dict[str, Any] | None] = (0, None, None)
    for path in ROADMAPS_DIR.glob("*.json"):
        if path.name == "_conversion_summary.json":
            continue
        data = load_json(path)
        score = roadmap_score(skill, path.stem, data)
        if score > best[0]:
            best = (score, path.stem, data)
    return best[1], best[2]


def extract_nodes(roadmap: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    node_map: dict[str, dict[str, Any]] = {}
    for phase in roadmap.get("phases", []):
        for node in phase.get("nodes", []):
            row = dict(node)
            row["_phase_id"] = phase.get("phase_id")
            row["_phase_title"] = phase.get("phase_title")
            row["_phase_order"] = phase.get("phase_order", 99)
            rows.append(row)
            node_map[row["node_id"]] = row
    return rows, node_map


def dependency_closure(selected: set[str], node_map: dict[str, dict[str, Any]]) -> set[str]:
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


def score_node(skill: str, node: dict[str, Any]) -> int:
    skill_tokens = split_tokens(skill)
    text = " ".join(
        str(node.get(key, ""))
        for key in ("label", "skill_key", "category", "_phase_title")
    )
    node_tokens = split_tokens(text)
    if not skill_tokens or not node_tokens:
        return 0

    score = len(skill_tokens.intersection(node_tokens))
    if normalize_text(skill) in normalize_text(text):
        score += 3
    if node.get("type") == "topic":
        score += 1
    if node.get("importance") == "core":
        score += 1
    return score


def deterministic_select(entry: dict[str, Any], rows: list[dict[str, Any]], node_map: dict[str, dict[str, Any]]) -> set[str]:
    skill = entry["skill"]
    user_level = to_int(entry.get("user_level"))
    required_level = to_int(entry.get("required_level"))
    gap = max(1, to_int(entry.get("gap"), max(1, required_level - user_level)))

    scored = [(score_node(skill, row), row) for row in rows]
    scored = [(score, row) for score, row in scored if score > 0]
    if not scored:
        scored = [(1, row) for row in rows if row.get("type") == "topic" and row.get("importance") == "core"]

    if user_level > 0:
        limit = min(len(scored), max(6, gap * 8))
        scored.sort(key=lambda item: (-item[1].get("_phase_order", 0), -item[0], item[1].get("node_id", "")))
    else:
        limit = min(len(scored), max(10, gap * 5, required_level * 5))
        scored.sort(key=lambda item: (-item[0], item[1].get("_phase_order", 99), item[1].get("node_id", "")))

    return dependency_closure({row["node_id"] for _, row in scored[:limit]}, node_map)


def resolve_llm_ids(raw_ids: list[Any], rows: list[dict[str, Any]]) -> list[str]:
    valid_ids = {row["node_id"] for row in rows}
    label_to_id = {normalize_text(row.get("label")): row["node_id"] for row in rows}
    suffix_to_id = {row["node_id"].split("--", 1)[-1]: row["node_id"] for row in rows}

    resolved: list[str] = []
    for raw in raw_ids:
        if not isinstance(raw, str):
            continue
        value = raw.strip()
        key = normalize_text(value)
        if value in valid_ids:
            resolved.append(value)
        elif value in suffix_to_id:
            resolved.append(suffix_to_id[value])
        elif key in label_to_id:
            resolved.append(label_to_id[key])
    return list(dict.fromkeys(resolved))


def llm_select_nodes_for_skill_gap(
    client: Groq | None,
    model: str,
    entry: dict[str, Any],
    roadmap_id: str,
    rows: list[dict[str, Any]],
) -> list[str]:
    if client is None:
        return []

    compact_nodes = [
        {
            "node_id": row["node_id"],
            "label": row.get("label"),
            "type": row.get("type"),
            "category": row.get("category"),
            "importance": row.get("importance"),
            "phase_title": row.get("_phase_title"),
            "depends_on": row.get("depends_on", []),
        }
        for row in rows
    ]

    prompt = {
        "role": "roadmap node selection agent",
        "instruction": (
            "The skill is from the skill_gaps category, so use the given roadmap "
            "as the source of truth and decide which node_ids should be present "
            "to close only this user's gap. Return JSON only."
        ),
        "skill_gap_entry": entry,
        "roadmap_id": roadmap_id,
        "available_nodes": compact_nodes,
        "rules": [
            "Return only node ids from available_nodes.",
            "Prefer nodes at or above current level; skip basics already known.",
            "Keep the result focused on the gap, not the full roadmap.",
            "Include prerequisite node ids only when required for selected nodes.",
        ],
        "output_schema": {"selected_node_ids": ["node-id"]},
    }

    response = client.chat.completions.create(
        model=model,
        temperature=0.1,
        messages=[
            {"role": "system", "content": "You are a strict JSON roadmap selection agent."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=True)},
        ],
    )
    raw = response.choices[0].message.content or ""

    parsed_obj = safe_parse_json(raw, expected_type=dict)
    if isinstance(parsed_obj, dict) and isinstance(parsed_obj.get("selected_node_ids"), list):
        return resolve_llm_ids(parsed_obj["selected_node_ids"], rows)

    parsed_list = safe_parse_json(raw, expected_type=list)
    if isinstance(parsed_list, list):
        return resolve_llm_ids(parsed_list, rows)

    return []


def sort_nodes_topologically(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    node_map = {node["node_id"]: node for node in nodes}
    seen: set[str] = set()
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


def build_phases(roadmap: dict[str, Any], roadmap_id: str, entry: dict[str, Any], selected_ids: set[str]) -> list[dict[str, Any]]:
    phases: list[dict[str, Any]] = []
    skill_status = entry.get("status", "locked")
    for phase in roadmap.get("phases", []):
        nodes: list[dict[str, Any]] = []
        for node in phase.get("nodes", []):
            if node.get("node_id") not in selected_ids:
                continue
            node_id = node["node_id"]
            prefixed = {
                **node,
                "node_id": f"{roadmap_id}--{node_id}",
                "depends_on": [f"{roadmap_id}--{dep}" for dep in node.get("depends_on", []) if dep in selected_ids],
                "matched_skill": entry["skill"],
                "source_roadmap": roadmap_id,
                "original_node_id": node_id,
                "skill_status": skill_status,
                "skill_priority": entry.get("priority", ""),
                "skill_importance": entry.get("importance", ""),
            }
            if skill_status == "in_progress" and not prefixed["depends_on"]:
                prefixed["status"] = "available"
            nodes.append(prefixed)
        if nodes:
            phases.append(
                {
                    "phase_id": f"{roadmap_id}--{phase.get('phase_id')}",
                    "phase_title": phase.get("phase_title", "Phase"),
                    "phase_order": phase.get("phase_order", 99),
                    "skill": entry["skill"],
                    "source": "standard_roadmap",
                    "nodes": sort_nodes_topologically(nodes),
                }
            )
    return phases


def build_edges(phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
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


def assemble_roadmap(state: AgentState) -> dict[str, Any]:
    profile = state.skill_gap.get("user_profile", {})
    readiness = state.skill_gap.get("readiness_summary", {})

    for index, phase in enumerate(state.phases, start=1):
        phase["phase_order"] = index

    edges = build_edges(state.phases)
    total_nodes = sum(len(phase.get("nodes", [])) for phase in state.phases)

    return {
        "roadmap_id": f"roadmap-agent--{profile.get('employee_id', 'unknown')}",
        "roadmap_title": f"Roadmap Agent - {profile.get('name', '')} -> {profile.get('target_role', '')}",
        "version": "1.0.0",
        "generated_with": "roadmap-agent",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "metadata": {
            "employee_id": profile.get("employee_id"),
            "name": profile.get("name"),
            "current_role": profile.get("current_role"),
            "target_role": profile.get("target_role"),
            "experience_years": profile.get("experience_years"),
            "readiness_score": readiness.get("readiness_score"),
            "readiness_category": readiness.get("readiness_category"),
            "readiness_message": readiness.get("readiness_message"),
            "total_phases": len(state.phases),
            "total_nodes": total_nodes,
            "total_edges": len(edges),
            "source_roadmaps": state.source_roadmaps,
            "uncovered_skills": sorted(set(state.uncovered_skills)),
            "agent_issues": state.issues,
            "agent_trace_summary": state.trace_summary,
        },
        "phases": state.phases,
        "edges": edges,
    }


def validate_roadmap(roadmap: dict[str, Any], skill_entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    nodes = [node for phase in roadmap.get("phases", []) for node in phase.get("nodes", [])]
    node_ids = {node.get("node_id") for node in nodes}
    matched = {node.get("matched_skill") for node in nodes if node.get("matched_skill")}

    for entry in skill_entries:
        if entry["skill"] not in matched:
            issues.append({"severity": "critical", "code": "missing_skill_coverage", "skill": entry["skill"]})

    for node in nodes:
        for dep in node.get("depends_on", []) or []:
            if dep not in node_ids:
                issues.append({"severity": "high", "code": "dangling_dependency", "node": node.get("node_id", "")})

    for edge in roadmap.get("edges", []):
        if edge.get("source") not in node_ids or edge.get("target") not in node_ids:
            issues.append({"severity": "high", "code": "dangling_edge", "edge": json.dumps(edge)})

    return issues


def run_agent(skill_gap_path: Path, output_path: Path, model: str) -> dict[str, Any]:
    trace = AgentTrace()
    trace.add(
        "observe",
        "Starting roadmap agent run",
        input_file=str(skill_gap_path),
        output_file=str(output_path),
        model=model,
    )

    skill_gap = load_json(skill_gap_path)
    trace.add("tool_call", "Loaded skill gap JSON", tool="load_json", output={"top_level_keys": list(skill_gap.keys())})

    skill_entries = extract_skill_entries(skill_gap)
    trace.add(
        "tool_call",
        "Extracted skill entries",
        tool="extract_skill_entries",
        output={"skills": [entry["skill"] for entry in skill_entries]},
    )

    client = make_client()
    trace.add(
        "observe",
        "Checked LLM client availability",
        llm_available=client is not None,
        credential_source="GROQ_API_KEY_or_LLM_GROQ_KEY" if client is not None else "none",
    )

    state = AgentState(skill_gap=skill_gap, model=model)

    ordered_entries = sorted(skill_entries, key=lambda entry: 0 if entry["bucket"] == "skill_gaps" else 1)
    trace.add(
        "decision",
        "Decided skill processing order",
        reason_code="skill_gaps_first_then_missing_skills",
        skill_order=[{"skill": entry["skill"], "bucket": entry["bucket"]} for entry in ordered_entries],
    )

    print("Roadmap Agent")
    print(f"Input : {skill_gap_path}")
    print(f"Output: {output_path}")
    print(f"Skills: {[entry['skill'] for entry in ordered_entries]}")

    for entry in ordered_entries:
        skill = entry["skill"]
        roadmap_id, roadmap = resolve_roadmap(skill)
        trace.add(
            "tool_call",
            "Resolved roadmap for skill",
            tool="resolve_roadmap",
            input={"skill": skill},
            output={"roadmap_id": roadmap_id, "found": bool(roadmap)},
        )

        if not roadmap_id or not roadmap:
            print(f"- {skill}: no roadmap found")
            trace.add(
                "decision",
                "Marked skill uncovered because no roadmap was found",
                skill=skill,
                reason_code="roadmap_not_found",
            )
            state.uncovered_skills.append(skill)
            continue

        rows, node_map = extract_nodes(roadmap)
        trace.add(
            "tool_call",
            "Extracted roadmap nodes",
            tool="extract_nodes",
            input={"roadmap_id": roadmap_id},
            output={"node_count": len(rows)},
        )

        if entry["bucket"] == "skill_gaps":
            print(f"- {skill}: skill_gaps category -> sending {roadmap_id} roadmap to LLM")
            trace.add(
                "decision",
                "Skill is in skill_gaps, so use LLM node selection",
                skill=skill,
                roadmap_id=roadmap_id,
                reason_code="skill_gap_requires_llm_selection",
            )
            selected = set(llm_select_nodes_for_skill_gap(client, model, entry, roadmap_id, rows))
            trace.add(
                "tool_call",
                "LLM selected roadmap nodes for skill gap",
                tool="llm_select_nodes_for_skill_gap",
                input={"skill": skill, "roadmap_id": roadmap_id, "available_nodes": len(rows)},
                output={"selected_nodes": len(selected)},
            )
            if not selected:
                print(f"  LLM selection empty; using deterministic fallback for {skill}")
                trace.add(
                    "fallback",
                    "LLM returned no usable nodes, using deterministic selector",
                    skill=skill,
                    reason_code="llm_empty_or_unavailable",
                )
                selected = deterministic_select(entry, rows, node_map)
                trace.add(
                    "tool_call",
                    "Selected nodes with deterministic fallback",
                    tool="deterministic_select",
                    input={"skill": skill, "roadmap_id": roadmap_id},
                    output={"selected_nodes": len(selected)},
                )
        else:
            print(f"- {skill}: {entry['bucket']} -> focused deterministic selection from {roadmap_id}")
            trace.add(
                "decision",
                "Skill is missing/optional, so use focused deterministic selection",
                skill=skill,
                roadmap_id=roadmap_id,
                bucket=entry["bucket"],
                reason_code="missing_skill_uses_focused_selection",
            )
            selected = deterministic_select(entry, rows, node_map)
            trace.add(
                "tool_call",
                "Selected focused roadmap nodes",
                tool="deterministic_select",
                input={"skill": skill, "roadmap_id": roadmap_id},
                output={"selected_nodes": len(selected)},
            )

        before_closure = len(selected)
        selected = dependency_closure(selected, node_map)
        trace.add(
            "tool_call",
            "Applied dependency closure",
            tool="dependency_closure",
            input={"skill": skill, "selected_before": before_closure},
            output={"selected_after": len(selected)},
        )

        phases = build_phases(roadmap, roadmap_id, entry, selected)
        trace.add(
            "tool_call",
            "Built output phases for skill",
            tool="build_phases",
            input={"skill": skill, "roadmap_id": roadmap_id, "selected_nodes": len(selected)},
            output={"phase_count": len(phases), "node_count": sum(len(phase.get("nodes", [])) for phase in phases)},
        )

        if not phases:
            trace.add(
                "decision",
                "Marked skill uncovered because no phases were produced",
                skill=skill,
                reason_code="empty_phase_output",
            )
            state.uncovered_skills.append(skill)
            continue

        state.phases.extend(phases)
        if roadmap_id not in state.source_roadmaps:
            state.source_roadmaps.append(roadmap_id)

    roadmap = assemble_roadmap(state)
    trace.add(
        "tool_call",
        "Assembled roadmap before validation",
        tool="assemble_roadmap",
        output={
            "total_nodes": roadmap["metadata"]["total_nodes"],
            "total_edges": roadmap["metadata"]["total_edges"],
            "total_phases": roadmap["metadata"]["total_phases"],
        },
    )

    state.issues = validate_roadmap(roadmap, skill_entries)
    trace.add(
        "validation",
        "Validated generated roadmap",
        tool="validate_roadmap",
        output={"issue_count": len(state.issues), "issues": state.issues},
    )

    state.trace_summary = trace.summary()
    roadmap = assemble_roadmap(state)
    save_json(output_path, roadmap)
    trace.add(
        "tool_call",
        "Saved generated roadmap JSON",
        tool="save_json",
        output={"path": str(output_path)},
    )

    state.trace_summary = trace.summary()
    roadmap = assemble_roadmap(state)
    save_json(output_path, roadmap)
    trace.save(TRACE_OUTPUT)
    save_agent_report(REPORT_OUTPUT, trace, roadmap)

    print(f"Saved: {output_path}")
    print(f"Trace: {TRACE_OUTPUT}")
    print(f"Report: {REPORT_OUTPUT}")
    print(f"Nodes: {roadmap['metadata']['total_nodes']}")
    print(f"Edges: {roadmap['metadata']['total_edges']}")
    print(f"Issues: {len(state.issues)}")
    return roadmap


def main() -> None:
    parser = argparse.ArgumentParser(description="Roadmap generation agent")
    parser.add_argument("--skill-gap", type=Path, default=DEFAULT_SKILL_GAP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()
    roadmap = run_agent(args.skill_gap, args.output, args.model)
    
    # LLM decides if resource allocation is needed
    if should_allocate_resources(roadmap, args.model):
        print("\n" + "=" * 60)
        print("  Initiating Resource Allocation...")
        print("=" * 60 + "\n")
        try:
            ra_trace = RAAgentTrace()
            summary = run_resource_agent(ra_trace)
            print(f"\n✅ Resource allocation completed!")
            print(f"   - Nodes: {summary['generated_nodes']}/{summary['total_nodes']}")
            print(f"   - Videos: {summary['total_videos']}")
            if summary['failures']:
                print(f"   - Failures: {summary['failed_nodes']}")
        except Exception as exc:
            print(f"⚠️  Resource allocation skipped: {exc}")
    else:
        print("\n💡 Resource allocation not needed at this time.")


def should_allocate_resources(roadmap: dict[str, Any], model: str) -> bool:
    """Ask LLM if resource allocation should run."""
    client = make_client()
    if not client:
        return True  # Default to True if no LLM
    
    metadata = roadmap.get("metadata", {})
    prompt = {
        "role": "resource allocation decision agent",
        "task": "Decide if the generated roadmap needs YouTube video resources mapped to each node",
        "roadmap_summary": {
            "total_nodes": metadata.get("total_nodes"),
            "total_phases": metadata.get("total_phases"),
            "total_edges": metadata.get("total_edges"),
            "uncovered_skills": metadata.get("uncovered_skills", []),
        },
        "decision_rules": [
            "Answer 'yes' if roadmap has nodes that need learning resources",
            "Answer 'no' if roadmap is incomplete or has critical issues",
            "Respond with exactly: YES or NO",
        ],
    }
    
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.1,
            messages=[
                {"role": "system", "content": "You are a decision agent. Respond with YES or NO only."},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=True)},
            ],
        )
        decision_text = (response.choices[0].message.content or "").strip().upper()
        return "YES" in decision_text
    except Exception as exc:
        print(f"LLM decision failed: {exc}. Proceeding with resource allocation.")
        return True
if __name__ == "__main__":
    main()
