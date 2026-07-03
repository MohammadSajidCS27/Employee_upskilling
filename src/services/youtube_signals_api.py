import requests
import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

class YouTubeSignalsAPI:
    def __init__(self, api_key: Optional[str] = None, search_keywords: Optional[List[str]] = None):
        self.api_key = api_key
        self.search_keywords = [keyword.strip().lower() for keyword in (search_keywords or []) if keyword.strip()]
        self.base_url = "https://www.googleapis.com/youtube/v3"
        self.request_timeout_seconds = 2

    def _get_fallback_skills(self) -> List[str]:
        """Modern 2026 trending skills when YouTube API unavailable."""
        return [
            "ai agents", "rag", "llm", "genai", "prompt engineering",
            "next.js", "vue", "svelte", "astro", "qwik",
            "tailwind", "shadcn", "framer motion", "radix ui",
            "kubernetes", "terraform", "helm", "argo cd", "kustomize",
            "docker", "podman", "containerd", "wasm",
            "python", "typescript", "rust", "go", "zod", "biome",
            "jest", "vitest", "playwright", "storybook",
            "tanstack query", "zustand", "jotai", "valtio",
            "github actions", "gitlab ci", "circleci",
            "supabase", "firebase", "planetscale", "neon",
            "langchain", "llamaindex", "transformers", "huggingface",
            "llmops", "mlops", "ai safety", "fine tuning",
        ]

    def get_technology_trends(self, max_results: int = 20) -> List[str]:
        """Get trending technology skills from YouTube"""
        skills = []
        
        if not self.api_key:
            logger.warning("YouTube API key not provided - returning modern tech fallback skills")
            return self._get_fallback_skills()
        
        try:
            keyword_pool = self.search_keywords or [
                "ai agent tutorial", "rag development", "llm tutorial", "generative ai",
                "python tutorial", "next.js react", "kubernetes docker", "terraform aws",
            ]
            query_limit = max(1, min(len(keyword_pool), max_results))

            for keyword in keyword_pool[:query_limit]:
                response = requests.get(
                    f"{self.base_url}/search",
                    params={
                        "part": "snippet",
                        "q": keyword,
                        "type": "video",
                        "order": "date",
                        "maxResults": 5,
                        "key": self.api_key
                    },
                    timeout=self.request_timeout_seconds,
                )
                if response.status_code == 200:
                    items = response.json().get("items", [])
                    for item in items:
                        title = item.get("snippet", {}).get("title", "").lower()
                        # Extract technology skills from video titles
                        for pattern in ["python", "java", "javascript", "typescript", "react", "vue", "angular",
                                        "next.js", "svelte", "docker", "kubernetes", "aws", "azure", "gcp",
                                        "terraform", "ai", "ml", "llm", "rag", "genai", "tailwind", "spring",
                                        "django", "flask", "fastapi", "nodejs", "express", "graphql", "grpc"]:
                            if pattern in title and pattern not in skills:
                                skills.append(pattern)
        except Exception as e:
            logger.error(f"YouTube API error: {e}")
        
        return list(set(skills)) if skills else self._get_fallback_skills()

    def get_emerging_skills(self, keywords: Optional[List[str]] = None, max_results: int = 20) -> List[str]:
        """Compatibility adapter used by market tools to retrieve emerging skills."""
        if keywords:
            self.search_keywords = [keyword.strip().lower() for keyword in keywords if str(keyword).strip()]
        return self.get_technology_trends(max_results=max_results)