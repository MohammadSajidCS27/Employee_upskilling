"""
Shared YouTube API client for fetching and formatting video recommendations.
Consolidates logic from project/youtube.py and resource_allocation_agent.py
"""

import os
import re
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_WEB_SEARCH_URL = "https://www.youtube.com/results"


class YouTubeClientError(RuntimeError):
    """Base error for YouTube client failures."""


class YouTubeAuthError(YouTubeClientError):
    """Raised when the YouTube API key is invalid or unauthorized."""


def validate_youtube_api_key() -> tuple[bool, str]:
    """Return whether the API key looks usable along with a reason when invalid."""
    key = (os.getenv("youtube_api_key") or os.getenv("YOUTUBE_API_KEY", "")).strip()
    if not key:
        return False, "missing API key"

    placeholder_values = {"YOUR_API_KEY", "CHANGE_ME", "NONE", "NULL", "N/A"}
    if key.upper() in placeholder_values:
        return False, "placeholder API key"

    # Standard Google API keys begin with AIza; reject obviously wrong tokens early.
    if not key.startswith("AIza") or len(key) < 30:
        return False, "invalid API key format"

    return True, ""


def get_youtube_api_key() -> str:
    """Get YouTube API key from environment."""
    ok, reason = validate_youtube_api_key()
    if not ok:
        raise YouTubeClientError(
            f"YouTube API key not usable ({reason}); set YOUTUBE_API_KEY or youtube_api_key in .env"
        )
    return (os.getenv("youtube_api_key") or os.getenv("YOUTUBE_API_KEY", "")).strip()


def fetch_videos(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """
    Fetch videos from YouTube API.
    
    Args:
        query: Search query (e.g., "java--learn-the-basics" or "Spring Boot tutorial")
        max_results: Maximum number of results to return (default 5)
    
    Returns:
        List of raw YouTube API items
    """
    params = {
        "key": get_youtube_api_key(),
        "q": f"{query} tutorial",
        "part": "snippet",
        "type": "video",
        "maxResults": max_results,
    }
    try:
        response = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=20)
        response.raise_for_status()
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code in (401, 403):
            raise YouTubeAuthError("YouTube API authorization failed") from exc
        raise YouTubeClientError(f"YouTube API request failed with status {status_code}") from exc
    except requests.RequestException as exc:
        raise YouTubeClientError("YouTube API request failed") from exc

    return response.json().get("items", [])


def fetch_videos_from_search_page(query: str, max_results: int = 2) -> list[dict[str, Any]]:
    """Best-effort fallback: parse YouTube web search results for video IDs (no API key)."""
    params = {"search_query": query}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(
            YOUTUBE_WEB_SEARCH_URL,
            params=params,
            headers=headers,
            timeout=20,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise YouTubeClientError("YouTube web search fallback request failed") from exc

    # Extract distinct 11-char video IDs that appear in page JSON.
    ids = []
    for video_id in re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', response.text):
        if video_id not in ids:
            ids.append(video_id)
        if len(ids) >= max_results:
            break

    videos = []
    for index, video_id in enumerate(ids):
        videos.append(
            {
                "video_id": video_id,
                "title": f"Recommended result {index + 1} for {query}",
                "channel": "YouTube",
                "thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
                "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
                "score": 6,
                "is_search_link": False,
            }
        )
    return videos


def format_videos(api_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Format raw YouTube API results into clean video objects.
    
    Args:
        api_results: Raw items from YouTube API
    
    Returns:
        List of formatted video dicts with video_id, title, channel, thumbnail, score
    """
    videos = []
    for item in api_results:
        video_id = item.get("id", {}).get("videoId")
        snippet = item.get("snippet", {})
        if not video_id:
            continue
        videos.append({
            "video_id": video_id,
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
            "score": 10,
        })
    return videos


def node_id_to_query(node_id: str) -> str:
    """
    Convert node_id (e.g., "java--learn-the-basics") to YouTube search query.
    
    Args:
        node_id: Node ID with -- and - separators
    
    Returns:
        Human-readable search query
    """
    return node_id.replace("--", " ").replace("-", " ")
