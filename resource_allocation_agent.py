"""
Resource Allocation Agent

Runs after roadmap agent to:
1. Load generated-roadmap.json
2. Store all nodes to DB
3. Fetch YouTube videos for each node
4. Create node-video mappings
5. Generate trace and report
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from youtube_client import fetch_videos, format_videos, node_id_to_query

# Keep ROOT aligned with the repository root (the folder containing this file).
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg2

load_dotenv()

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────

ROADMAP_SOURCE = ROOT / "generated-roadmap.json"
AGENT_OUTPUT_DIR = ROOT / "resource_allocation_agent"
TRACE_FILE = AGENT_OUTPUT_DIR / "agent_trace.json"
REPORT_FILE = AGENT_OUTPUT_DIR / "agent_report.md"

DEFAULT_MODEL = "resource-allocation-v1"
DEFAULT_ROADMAP_SLUG = "generated"

# ──────────────────────────────────────────────
# DB Connection
# ──────────────────────────────────────────────

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "postgres"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "Vamshi@27"),
    )

# ──────────────────────────────────────────────
# YouTube API
# ──────────────────────────────────────────────

# ──────────────────────────────────────────────
# Utils
# ──────────────────────────────────────────────

def load_roadmap_nodes(source_path: Path | None = None) -> list[dict[str, Any]]:
    """Load all nodes from generated-roadmap.json."""
    src = source_path or ROADMAP_SOURCE
    if not src.exists():
        raise FileNotFoundError(f"Roadmap not found: {src}")
    
    roadmap = json.loads(src.read_text(encoding="utf-8"))
    nodes: list[dict[str, Any]] = []
    
    for phase in roadmap.get("phases", []):
        for node in phase.get("nodes", []):
            node_id = node.get("node_id")
            if node_id:
                nodes.append({
                    "node_id": node_id,
                    "title": node.get("label") or node_id,
                    "role": roadmap.get("metadata", {}).get("target_role"),
                    "roadmap_slug": DEFAULT_ROADMAP_SLUG,
                })
    
    return nodes



def node_has_cached_videos(connection, node_id: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM node_video_mapping WHERE node_id = %s LIMIT 1",
            (node_id,),
        )
        return cursor.fetchone() is not None

# ──────────────────────────────────────────────
# Agent Trace
# ──────────────────────────────────────────────

class AgentTrace:
    def __init__(self):
        self.events: list[dict[str, Any]] = []
        self.step = 0

    def add(self, event_type: str, message: str, **data: Any) -> None:
        self.step += 1
        self.events.append({
            "step": self.step,
            "type": event_type,
            "message": message,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **data,
        })

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"events": self.events}, indent=2),
            encoding="utf-8"
        )

# ──────────────────────────────────────────────
# Main Agent Logic
# ──────────────────────────────────────────────

def run_agent(trace: AgentTrace, roadmap_source: Path | None = None) -> dict[str, Any]:
    """Run resource allocation agent."""
    
    # Step 1: Load roadmap
    trace.add("observe", "Loading roadmap from generated-roadmap.json")
    nodes = load_roadmap_nodes(roadmap_source)
    trace.add("tool_call", "Loaded roadmap nodes", count=len(nodes))
    
    connection = get_db_connection()
    
    # Step 2: Store nodes to DB
    trace.add("decide", "Syncing nodes to database")
    with connection.cursor() as cursor:
        for node in nodes:
            cursor.execute(
                """
                INSERT INTO roadmap_nodes (node_id, title, role, roadmap_slug)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (node_id) DO UPDATE
                SET title = EXCLUDED.title,
                    role = EXCLUDED.role,
                    roadmap_slug = EXCLUDED.roadmap_slug;
                """,
                (node["node_id"], node["title"], node["role"], node["roadmap_slug"]),
            )
    connection.commit()
    trace.add("tool_call", "Synced nodes to DB", nodes_stored=len(nodes))
    
    # Step 3: Generate videos for each node
    trace.add("decide", "Generating YouTube videos for all nodes")
    
    total_nodes = len(nodes)
    generated_nodes = 0
    cached_nodes = 0
    skipped_nodes = 0
    total_videos = 0
    failures: list[dict[str, str]] = []
    quota_exhausted = False
    
    for idx, node in enumerate(nodes, start=1):
        node_id = node["node_id"]
        if quota_exhausted:
            skipped_nodes += 1
            trace.add(
                "warn",
                f"Skipping {node_id}; YouTube quota was exhausted earlier in the run",
                node_id=node_id,
            )
            continue

        try:
            if node_has_cached_videos(connection, node_id):
                cached_nodes += 1
                trace.add(
                    "cache_hit",
                    f"Using cached videos for {node_id}",
                    node_id=node_id,
                )
                continue

            query = node_id_to_query(node_id)
            trace.add("tool_call", f"Fetching videos for node {idx}/{total_nodes}", 
                     node_id=node_id, query=query)
            
            # Fetch and format
            api_results = fetch_videos(query)
            videos = format_videos(api_results)
            
            if not videos:
                trace.add("warn", f"No videos found for {node_id}")
                continue
            
            # Store videos and mappings
            with connection.cursor() as cursor:
                # Clear old mappings
                cursor.execute(
                    "DELETE FROM node_video_mapping WHERE node_id = %s",
                    (node_id,)
                )
                
                # Insert videos and mappings
                for rank, video in enumerate(videos, start=1):
                    cursor.execute(
                        """
                        INSERT INTO videos (video_id, title, channel, views, likes, duration, thumbnail, source_roadmap)
                        VALUES (%s, %s, %s, 0, 0, '', %s, %s)
                        ON CONFLICT (video_id) DO UPDATE
                        SET title = EXCLUDED.title, channel = EXCLUDED.channel, 
                            thumbnail = EXCLUDED.thumbnail,
                            source_roadmap = COALESCE(EXCLUDED.source_roadmap, source_roadmap);
                        """,
                        (video["video_id"], video["title"], video["channel"], video["thumbnail"], DEFAULT_ROADMAP_SLUG),
                    )
                    cursor.execute(
                        """
                        INSERT INTO node_video_mapping (node_id, video_id, score, rank)
                        VALUES (%s, %s, %s, %s);
                        """,
                        (node_id, video["video_id"], video["score"], rank),
                    )
            
            connection.commit()
            generated_nodes += 1
            total_videos += len(videos)
            
            trace.add("validation", f"Stored {len(videos)} videos for {node_id}",
                     node_id=node_id, video_count=len(videos))

        except requests.HTTPError as exc:
            connection.rollback()
            status_code = getattr(exc.response, "status_code", None)
            if status_code == 429:
                quota_exhausted = True
                skipped_nodes += 1
                trace.add(
                    "warn",
                    f"YouTube rate limit hit while processing {node_id}; remaining nodes will be skipped",
                    node_id=node_id,
                    error=str(exc),
                )
                continue

            error_msg = str(exc)
            failures.append({"node_id": node_id, "error": error_msg})
            trace.add("error", f"Failed to process {node_id}", 
                     node_id=node_id, error=error_msg)
            
        except Exception as exc:
            connection.rollback()
            error_msg = str(exc)
            failures.append({"node_id": node_id, "error": error_msg})
            trace.add("error", f"Failed to process {node_id}", 
                     node_id=node_id, error=error_msg)
    
    connection.close()
    
    # Summary
    summary = {
        "total_nodes": total_nodes,
        "generated_nodes": generated_nodes,
        "cached_nodes": cached_nodes,
        "skipped_nodes": skipped_nodes,
        "quota_exhausted": quota_exhausted,
        "total_videos": total_videos,
        "failed_nodes": len(failures),
        "failures": failures,
    }
    
    trace.add("observe", "Agent completed", summary=summary)
    
    return summary

def save_report(trace: AgentTrace, summary: dict[str, Any]) -> None:
    """Save markdown report."""
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    lines = [
        "# Resource Allocation Agent Report",
        "",
        "## Summary",
        f"- Total nodes processed: {summary['total_nodes']}",
        f"- Nodes with videos: {summary['generated_nodes']}",
        f"- Nodes served from cache: {summary.get('cached_nodes', 0)}",
        f"- Skipped nodes: {summary.get('skipped_nodes', 0)}",
        f"- Quota exhausted: {summary.get('quota_exhausted', False)}",
        f"- Total videos stored: {summary['total_videos']}",
        f"- Failed nodes: {summary['failed_nodes']}",
        "",
    ]
    
    if summary["failures"]:
        lines.extend([
            "## Failures",
            "",
        ])
        for fail in summary["failures"]:
            lines.append(f"- **{fail['node_id']}**: {fail['error']}")
        lines.append("")
    
    lines.extend([
        "## Trace Events",
        f"- Total events: {len(trace.events)}",
        "",
    ])
    
    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")

# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Resource Allocation Agent")
    print("=" * 60)
    print()
    
    trace = AgentTrace()
    
    try:
        summary = run_agent(trace)
        
        print(f"✅ Total nodes: {summary['total_nodes']}")
        print(f"✅ Generated: {summary['generated_nodes']}")
        print(f"✅ Cached: {summary.get('cached_nodes', 0)}")
        print(f"✅ Skipped: {summary.get('skipped_nodes', 0)}")
        print(f"✅ Quota exhausted: {summary.get('quota_exhausted', False)}")
        print(f"✅ Total videos: {summary['total_videos']}")
        
        if summary['failures']:
            print(f"⚠️  Failed: {summary['failed_nodes']}")
        
        # Save artifacts
        trace.save(TRACE_FILE)
        save_report(trace, summary)
        
        print()
        print(f"Trace:  {TRACE_FILE}")
        print(f"Report: {REPORT_FILE}")
        print()
        print("=" * 60)
        print("  Done! ✓")
        print("=" * 60)
        
    except Exception as exc:
        print(f"❌ Error: {exc}")
        trace.add("error", f"Agent failed: {exc}")
        trace.save(TRACE_FILE)
        sys.exit(1)

if __name__ == "__main__":
    main()


# """
# Resource Allocation Agent

# Runs after roadmap agent to:
# 1. Load generated-roadmap.json
# 2. Store all nodes to DB
# 3. Fetch YouTube videos for each node
# 4. Create node-video mappings
# 5. Generate trace and report
# """

# from __future__ import annotations

# import json
# import os
# import sys
# from datetime import datetime, timedelta
# from pathlib import Path
# from typing import Any
# import time

# import requests
# from dotenv import load_dotenv

# from youtube_client import (
#     # YouTubeApiError,
#     # YouTubeQuotaExceededError,
#     # YouTubeRateLimitedError,
#     fetch_videos,
#     format_videos,
#     node_id_to_query,
# )

# # Keep ROOT aligned with the repository root (the folder containing this file).
# ROOT = Path(__file__).resolve().parent
# if str(ROOT) not in sys.path:
#     sys.path.insert(0, str(ROOT))

# import psycopg2

# load_dotenv()

# # ────────────────────────────────────────────
# # Config
# # ───────────────────────────────────────────

# ROADMAP_SOURCE = Path("C:/Users/z005a42d/Desktop/vamshi/Agents/generated-roadmap.json")
# AGENT_OUTPUT_DIR = ROOT / "resource_allocation_agent"
# TRACE_FILE = AGENT_OUTPUT_DIR / "agent_trace.json"
# REPORT_FILE = AGENT_OUTPUT_DIR / "agent_report.md"

# DEFAULT_MODEL = "resource-allocation-v1"
# DEFAULT_ROADMAP_SLUG = "generated"
# CACHE_TTL_DAYS = 10

# # ──────────────────────────────────────────────
# # DB Connection
# # ──────────────────────────────────────────────

# def get_db_connection():
#     return psycopg2.connect(
#         host="localhost",
#         port=int("5432"),
#         database="postgres",
#         user="postgres",
#         password="Vamshi@27"
#     )

# # ──────────────────────────────────────────────
# # YouTube API
# # ──────────────────────────────────────────────

# # ──────────────────────────────────────────────
# # Utils
# # ──────────────────────────────────────────────

# def load_roadmap_nodes() -> list[dict[str, Any]]:
#     """Load all nodes from generated-roadmap.json."""
#     if not ROADMAP_SOURCE.exists():
#         raise FileNotFoundError(f"Roadmap not found: {ROADMAP_SOURCE}")
    
#     roadmap = json.loads(ROADMAP_SOURCE.read_text(encoding="utf-8"))
#     nodes: list[dict[str, Any]] = []
    
#     for phase in roadmap.get("phases", []):
#         for node in phase.get("nodes", []):
#             node_id = node.get("node_id")
#             if node_id:
#                 nodes.append({
#                     "node_id": node_id,
#                     "title": node.get("label") or node_id,
#                     "role": roadmap.get("metadata", {}).get("target_role"),
#                     "roadmap_slug": DEFAULT_ROADMAP_SLUG,
#                 })
#     print(f"Loaded {len(nodes)} nodes from roadmap")
#     return nodes


# def should_fetch_videos(connection, node_id: str, ttl_days: int = CACHE_TTL_DAYS) -> tuple[bool, str]:
#     """Return whether this node needs a fresh YouTube fetch.

#     Rules:
#     - No mappings -> fetch
#     - Mappings older than ttl_days -> fetch
#     - Recent mappings -> skip
#     """
#     with connection.cursor() as cursor:
#         cursor.execute(
#             """
#             SELECT COUNT(*) AS mapping_count, MAX(created_at) AS latest_created_at
#             FROM node_video_mapping
#             WHERE node_id = %s
#             """,
#             (node_id,),
#         )
#         mapping_count, latest_created_at = cursor.fetchone()

#     if mapping_count == 0:
#         return True, "missing"

#     if latest_created_at is None:
#         return True, "missing_timestamp"

#     now = datetime.now(latest_created_at.tzinfo) if latest_created_at.tzinfo else datetime.utcnow()
#     if (now - latest_created_at) > timedelta(days=ttl_days):
#         return True, "stale"

#     return False, "fresh"

# # ──────────────────────────────────────────────
# # Agent Trace
# # ──────────────────────────────────────────────

# class AgentTrace:
#     def __init__(self):
#         self.events: list[dict[str, Any]] = []
#         self.step = 0

#     def add(self, event_type: str, message: str, **data: Any) -> None:
#         self.step += 1
#         self.events.append({
#             "step": self.step,
#             "type": event_type,
#             "message": message,
#             "timestamp": datetime.utcnow().isoformat() + "Z",
#             **data,
#         })

#     def save(self, path: Path) -> None:
#         path.parent.mkdir(parents=True, exist_ok=True)
#         path.write_text(
#             json.dumps({"events": self.events}, indent=2),
#             encoding="utf-8"
#         )

# # ──────────────────────────────────────────────
# # Main Agent Logic
# # ──────────────────────────────────────────────

# def run_agent(trace: AgentTrace) -> dict[str, Any]:
#     """Run resource allocation agent."""
    
#     # Step 1: Load roadmap
#     trace.add("observe", "Loading roadmap from generated-roadmap.json")
#     nodes = load_roadmap_nodes()
#     trace.add("tool_call", "Loaded roadmap nodes", count=len(nodes))
    
#     connection = get_db_connection()
    
#     # Step 2: Store nodes to DB
#     trace.add("decide", "Syncing nodes to database")
#     with connection.cursor() as cursor:
#         for node in nodes:
#             cursor.execute(
#                 """
#                 INSERT INTO roadmap_nodes (node_id, title, role, roadmap_slug)
#                 VALUES (%s, %s, %s, %s)
#                 ON CONFLICT (node_id) DO UPDATE
#                 SET title = EXCLUDED.title,
#                     role = EXCLUDED.role,
#                     roadmap_slug = EXCLUDED.roadmap_slug;
#                 """,
#                 (node["node_id"], node["title"], node["role"], node["roadmap_slug"]),
#             )
#     connection.commit()
#     trace.add("tool_call", "Synced nodes to DB", nodes_stored=len(nodes))
    
#     # Step 3: Generate videos for each node
#     trace.add("decide", "Generating YouTube videos for all nodes")
    
#     total_nodes = len(nodes)
#     generated_nodes = 0
#     total_videos = 0
#     failures: list[dict[str, str]] = []
#     skipped_nodes = 0
#     cached_nodes = 0
#     no_videos_nodes = 0
#     quota_exhausted = False
    
#     for idx, node in enumerate(nodes, start=1):
#         node_id = node["node_id"]
#         try:
#             should_fetch, cache_reason = should_fetch_videos(connection, node_id)
#             if not should_fetch:
#                 cached_nodes += 1
#                 print(f"Cache hit for {node_id}; skipping API call")
#                 trace.add(
#                     "cache_hit",
#                     f"Skipping YouTube fetch for {node_id}; cached videos are fresh",
#                     node_id=node_id,
#                     cache_reason=cache_reason,
#                 )
#                 continue

#             if quota_exhausted:
#                 skipped_nodes += 1
#                 print(f"Skipped {node_id}; API refresh needed but quota is exhausted")
#                 trace.add(
#                     "warn",
#                     f"Skipped {node_id}; API refresh needed but quota is exhausted",
#                     node_id=node_id,
#                     cache_reason=cache_reason,
#                 )
#                 continue

#             print(f"Cache miss for {node_id}; refreshing from YouTube API")

#             trace.add(
#                 "cache_miss",
#                 f"Refreshing videos for {node_id}",
#                 node_id=node_id,
#                 cache_reason=cache_reason,
#             )

#             query = node_id_to_query(node_id)
#             trace.add("tool_call", f"Fetching videos for node {idx}/{total_nodes}", 
#                      node_id=node_id, query=query)
            
#             # Fetch and format
#             api_results = fetch_videos(query)
#             videos = format_videos(api_results)
            
#             if not videos:
#                 no_videos_nodes += 1
#                 trace.add("warn", f"No videos found for {node_id}")
#                 continue
            
#             # Store videos and mappings
#             with connection.cursor() as cursor:
#                 # Clear old mappings
#                 cursor.execute(
#                     "DELETE FROM node_video_mapping WHERE node_id = %s",
#                     (node_id,)
#                 )
                
#                 # Insert videos and mappings
#                 for rank, video in enumerate(videos, start=1):
#                     cursor.execute(
#                         """
#                         INSERT INTO videos (video_id, title, channel, views, likes, duration, thumbnail, source_roadmap)
#                         VALUES (%s, %s, %s, 0, 0, '', %s, %s)
#                         ON CONFLICT (video_id) DO UPDATE
#                         SET title = EXCLUDED.title, channel = EXCLUDED.channel, 
#                             thumbnail = EXCLUDED.thumbnail,
#                             source_roadmap = COALESCE(EXCLUDED.source_roadmap, videos.source_roadmap);
#                         """,
#                         (video["video_id"], video["title"], video["channel"], video["thumbnail"], DEFAULT_ROADMAP_SLUG),
#                     )
#                     cursor.execute(
#                         """
#                         INSERT INTO node_video_mapping (node_id, video_id, score, rank)
#                         VALUES (%s, %s, %s, %s);
#                         """,
#                         (node_id, video["video_id"], video["score"], rank),
#                     )
            
#             connection.commit()
#             generated_nodes += 1
#             total_videos += len(videos)
#             # Small pacing delay helps avoid short burst rate limiting.
#             time.sleep(0.2)
            
#             trace.add("validation", f"Stored {len(videos)} videos for {node_id}",
#                      node_id=node_id, video_count=len(videos))
            
#         # except YouTubeQuotaExceededError as exc:
#         #     connection.rollback()
#         #     error_msg = str(exc)
#         #     failures.append({"node_id": node_id, "error": error_msg})
#         #     quota_exhausted = True
#         #     trace.add(
#         #         "error",
#         #         f"Quota exhausted while processing {node_id}; remaining nodes will be skipped",
#         #         node_id=node_id,
#         #         error=error_msg,
#         #     )
#         # except (YouTubeRateLimitedError, YouTubeApiError) as exc:
#         #     connection.rollback()
#         #     error_msg = str(exc)
#         #     failures.append({"node_id": node_id, "error": error_msg})
#         #     trace.add("error", f"Failed to process {node_id}", 
#         #              node_id=node_id, error=error_msg)
#         except Exception as exc:
#             connection.rollback()
#             error_msg = str(exc)
#             failures.append({"node_id": node_id, "error": error_msg})
#             trace.add("error", f"Failed to process {node_id}", 
#                      node_id=node_id, error=error_msg)
    
#     connection.close()
    
#     # Summary
#     summary = {
#         "total_nodes": total_nodes,
#         "generated_nodes": generated_nodes,
#         "cached_nodes": cached_nodes,
#         "no_videos_nodes": no_videos_nodes,
#         "total_videos": total_videos,
#         "failed_nodes": len(failures),
#         "skipped_nodes": skipped_nodes,
#         "quota_exhausted": quota_exhausted,
#         "failures": failures,
#     }
    
#     trace.add("observe", "Agent completed", summary=summary)
    
#     return summary

# def save_report(trace: AgentTrace, summary: dict[str, Any]) -> None:
#     """Save markdown report."""
#     REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    
#     lines = [
#         "# Resource Allocation Agent Report",
#         "",
#         "## Summary",
#         f"- Total nodes processed: {summary['total_nodes']}",
#         f"- Nodes with videos: {summary['generated_nodes']}",
#         f"- Nodes served from cache: {summary.get('cached_nodes', 0)}",
#         f"- Nodes with no videos found: {summary.get('no_videos_nodes', 0)}",
#         f"- Total videos stored: {summary['total_videos']}",
#         f"- Failed nodes: {summary['failed_nodes']}",
#         f"- Skipped nodes (quota exhausted after cache miss): {summary.get('skipped_nodes', 0)}",
#         f"- Quota exhausted: {summary.get('quota_exhausted', False)}",
#         "",
#     ]
    
#     if summary["failures"]:
#         lines.extend([
#             "## Failures",
#             "",
#         ])
#         for fail in summary["failures"]:
#             lines.append(f"- **{fail['node_id']}**: {fail['error']}")
#         lines.append("")
    
#     lines.extend([
#         "## Trace Events",
#         f"- Total events: {len(trace.events)}",
#         "",
#     ])
    
#     REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")

# # ──────────────────────────────────────────────
# # Main
# # ──────────────────────────────────────────────

# def main():
#     print("=" * 60)
#     print("  Resource Allocation Agent")
#     print("=" * 60)
#     print()
    
#     trace = AgentTrace()
    
#     try:
#         summary = run_agent(trace)
        
#         print(f"✅ Total nodes: {summary['total_nodes']}")
#         print(f"✅ Already present in DB (cache hit): {summary.get('cached_nodes', 0)}")
#         print(f"✅ Fetched from API (cache miss): {summary['generated_nodes']}")
#         print(f"✅ No videos found from API: {summary.get('no_videos_nodes', 0)}")
#         print(f"✅ Skipped (quota exhausted after cache miss): {summary.get('skipped_nodes', 0)}")
#         print(f"✅ Generated: {summary['generated_nodes']}")
#         print(f"✅ Total videos: {summary['total_videos']}")

#         reconciled_total = (
#             summary.get('cached_nodes', 0)
#             + summary['generated_nodes']
#             + summary.get('no_videos_nodes', 0)
#             + summary.get('skipped_nodes', 0)
#             + summary['failed_nodes']
#         )
#         print(f"✅ Reconciled nodes count: {reconciled_total}/{summary['total_nodes']}")
        
#         if summary['failures']:
#             print(f"⚠️  Failed: {summary['failed_nodes']}")
        
#         # Save artifacts
#         trace.save(TRACE_FILE)
#         save_report(trace, summary)
        
#         print()
#         print(f"Trace:  {TRACE_FILE}")
#         print(f"Report: {REPORT_FILE}")
#         print()
#         print("=" * 60)
#         print("  Done! ✓")
#         print("=" * 60)
        
#     except Exception as exc:
#         print(f"❌ Error: {exc}")
#         trace.add("error", f"Agent failed: {exc}")
#         trace.save(TRACE_FILE)
#         sys.exit(1)

# if __name__ == "__main__":
#     main()
