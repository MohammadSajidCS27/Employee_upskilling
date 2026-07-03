import requests
import logging
from datetime import datetime, timedelta, UTC
from typing import List, Optional, Dict
from src.services.dynamic_defaults import default_github_languages

logger = logging.getLogger(__name__)

class GitHubTrendsAPI:
    def __init__(
        self,
        token: Optional[str] = None,
        languages: Optional[List[str]] = None,
        base_url: str = "https://api.github.com",
        trending_window_days: int = 365,
    ):
        self.token = token
        self.base_url = base_url
        self.languages = [lang.lower() for lang in (languages or default_github_languages())]
        self.trending_window_days = max(1, trending_window_days)
        self.request_timeout_seconds = 2
        self.headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            self.headers["Authorization"] = f"token {token}"

    def _get_fallback_skills(self) -> List[str]:
        """Modern 2026 trending skills when GitHub API unavailable."""
        return [
            "ai", "llm", "rag", "genai", "agentic ai", "mlops", "llmops",
            "python", "typescript", "rust", "go", "kotlin", "swift",
            "react", "next.js", "vue", "svelte", "astro", "qwik",
            "kubernetes", "docker", "terraform", "helm", "argocd", "serverless",
            "graphql", "rest api", "grpc", "websocket", "webhook",
            "tensorflow", "pytorch", "langchain", "llamaindex", "transformers",
            "aws", "azure", "gcp", "cloudflare", "supabase", "firebase",
            "tailwind", "shadcn", "radix ui", "framer motion",
            "jest", "vitest", "playwright", "cypress", "testing library",
            "github actions", "gitlab ci", "circleci", "argo workflows",
        ]

    def get_trending_skills(self, limit: int = 30) -> List[str]:
        """Get trending programming languages and tech skills from GitHub"""
        try:
            skills = set()
            since_date = (datetime.now(UTC) - timedelta(days=self.trending_window_days)).date().isoformat()
            for lang in self.languages:
                response = requests.get(
                    f"{self.base_url}/search/repositories",
                    params={"q": f"language:{lang} created:>{since_date}", "sort": "stars", "order": "desc", "per_page": limit},
                    headers=self.headers,
                    timeout=self.request_timeout_seconds,
                )
                if response.status_code == 200:
                    repos = response.json().get("items", [])
                    for repo in repos[:5]:
                        lang_name = repo.get("language")
                        if lang_name:
                            skills.add(lang_name.lower())
                        topics = repo.get("topics", [])
                        # Include all topic skills, not just alphanumeric
                        for t in topics[:15]:
                            skills.add(t.lower())
            # Add fallback skills for completeness
            skills.update(self._get_fallback_skills()[:20])
            return list(skills)
        except Exception as e:
            logger.error(f"GitHub trends error: {e}")
            return self._get_fallback_skills()

    def get_trending_repositories(self, limit: int = 20) -> List[dict]:
        """Get trending repositories from GitHub"""
        try:
            since_date = (datetime.now(UTC) - timedelta(days=self.trending_window_days)).date().isoformat()
            response = requests.get(
                f"{self.base_url}/search/repositories",
                params={"q": f"created:>{since_date}", "sort": "stars", "order": "desc", "per_page": limit},
                headers=self.headers,
                timeout=self.request_timeout_seconds,
            )
            response.raise_for_status()
            return response.json().get("items", [])
        except Exception as e:
            logger.error(f"GitHub repos error: {e}")
            return []

    def get_repo_languages(self, repo_name: str) -> List[str]:
        """Get languages used in a specific repository"""
        try:
            response = requests.get(
                f"{self.base_url}/repos/{repo_name}/languages",
                headers=self.headers,
                timeout=self.request_timeout_seconds,
            )
            if response.status_code == 200:
                return list(response.json().keys())
            return []
        except Exception as e:
            logger.error(f"GitHub languages error: {e}")
            return []