"""Market analysis tools for LangGraph/LangChain agents."""
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class MarketTools:
    """Toolbox for market trend and skill lifecycle analysis."""

    def __init__(
        self,
        esco_repo=None,
        onet_repo=None,
        google_trends=None,
        github_trends=None,
        youtube_signals=None,
        job_market_signals=None,
        tech_keywords: List[str] | None = None,
    ):
        self.esco_repo = esco_repo
        self.onet_repo = onet_repo
        self.google_trends = google_trends
        self.github_trends = github_trends
        self.youtube_signals = youtube_signals
        self.job_market_signals = job_market_signals
        self.tech_keywords = tech_keywords or []
        self.provider_timeout_seconds = 1  # Fast fallback to local data
        self._last_source_health: Dict[str, Dict[str, Any]] = {}
        self._last_source_trends: Dict[str, List[str]] = {}

    @property
    def last_source_health(self) -> Dict[str, Dict[str, Any]]:
        return self._last_source_health

    @property
    def last_source_trends(self) -> Dict[str, List[str]]:
        return self._last_source_trends

    def _update_source_health(self, source: str, status: str, count: int = 0, detail: str = "") -> None:
        self._last_source_health[source] = {
            "status": status,
            "count": max(0, int(count)),
            "detail": detail,
        }

    def _safe_provider_call(self, provider_name: str, fn):
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(fn)
            return {
                "status": "ok",
                "skills": future.result(timeout=self.provider_timeout_seconds) or [],
                "detail": "",
            }
        except FutureTimeoutError:
            logger.warning("%s provider timed out after %ss", provider_name, self.provider_timeout_seconds)
            future.cancel()
            return {
                "status": "timeout",
                "skills": [],
                "detail": f"Timed out after {self.provider_timeout_seconds}s",
            }
        except Exception as exc:
            logger.debug("%s provider call failed: %s", provider_name, exc)
            return {
                "status": "error",
                "skills": [],
                "detail": str(exc)[:200],
            }
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def collect_emerging_skills(self, keywords: List[str] | None = None, role: str = "") -> Dict[str, Dict[str, Any]]:
        from src.services.dynamic_defaults import default_role_trending_skills
        
        emerging: Dict[str, Dict[str, Any]] = {}
        self._last_source_health = {}
        self._last_source_trends = {}
        active_keywords = [str(k).strip() for k in (keywords or self.tech_keywords) if str(k).strip()]
        active_role = str(role or "").strip().lower()

        # 1. Role-specific trending skills - priority matching by role name
        role_skills = []
        all_role_skills = default_role_trending_skills()
        for role_key, skills in all_role_skills.items():
            # Match if role keyword appears in either role_key or any tech keyword
            role_key_lower = role_key.lower()
            if role_key_lower in active_role or active_role in role_key_lower:
                role_skills.extend(skills)
            else:
                for kw in (keywords or self.tech_keywords or []):
                    kw_lower = kw.lower()
                    if role_key_lower in kw_lower or kw_lower in role_key_lower:
                        role_skills.extend(skills)
                        break
        
        for skill in role_skills:
            cleaned = str(skill).strip().lower()
            if cleaned and cleaned not in emerging:
                emerging[cleaned] = {"source": "role-trending", "confidence": 0.95, "lifecycle_score": 0.9}
        self._last_source_trends["role-trending"] = list(emerging.keys())

        # 1. ESCO - skill search terms
        if self.esco_repo:
            added = 0
            for keyword in active_keywords[:5]:
                try:
                    results = self.esco_repo.search_skill(keyword)
                    for skill in results[:3]:
                        text = skill.get("preferredLabel", {}).get("en", "") or skill.get("searchHit", "")
                        cleaned = str(text).strip().lower()
                        if cleaned and cleaned not in emerging:
                            emerging[cleaned] = {"source": "esco", "confidence": 0.95}
                            added += 1
                except Exception as exc:
                    logger.debug("ESCO market lookup failed for %s: %s", keyword, exc)
            self._update_source_health("esco", "ok" if added else "empty", count=added)
            self._last_source_trends["esco"] = [
                skill for skill, detail in emerging.items() if detail.get("source") == "esco"
            ]
        else:
            self._update_source_health("esco", "unavailable", detail="ESCO repository not configured")
            self._last_source_trends["esco"] = []

        # 2. O*NET trending skills
        if self.onet_repo:
            onet_result = self._safe_provider_call("O*NET", self.onet_repo.get_trending_skills)
            skills = onet_result["skills"]
            added = 0
            for skill in skills:
                cleaned = str(skill).strip().lower()
                if cleaned and cleaned not in emerging:
                    emerging[cleaned] = {"source": "onet", "confidence": 0.9}
                    added += 1
            if onet_result["status"] == "ok":
                self._update_source_health("onet", "ok" if added else "empty", count=added)
            else:
                self._update_source_health("onet", onet_result["status"], count=0, detail=onet_result["detail"])
            self._last_source_trends["onet"] = [
                skill for skill, detail in emerging.items() if detail.get("source") == "onet"
            ]
        else:
            self._update_source_health("onet", "unavailable", detail="O*NET repository not configured")
            self._last_source_trends["onet"] = []

        # 3. GitHub Trends
        if self.github_trends:
            github_result = self._safe_provider_call("GitHub", self.github_trends.get_trending_skills)
            skills = github_result["skills"]
            if github_result["status"] != "ok" and hasattr(self.github_trends, "_get_fallback_skills"):
                skills = self.github_trends._get_fallback_skills()
            added = 0
            for skill in skills:
                cleaned = str(skill).strip().lower()
                if cleaned and cleaned not in emerging:
                    emerging[cleaned] = {"source": "github", "confidence": 0.7}
                    added += 1
            self._update_source_health("github", "ok" if added else "empty", count=added)
            self._last_source_trends["github"] = [
                skill for skill, detail in emerging.items() if detail.get("source") == "github"
            ]
        else:
            self._update_source_health("github", "unavailable", detail="GitHub trends source not configured")
            self._last_source_trends["github"] = []

        # 4. YouTube Signals
        if self.youtube_signals:
            youtube_callable = None
            if hasattr(self.youtube_signals, "get_emerging_skills"):
                youtube_callable = lambda: self.youtube_signals.get_emerging_skills(active_keywords)
            elif hasattr(self.youtube_signals, "get_technology_trends"):
                youtube_callable = lambda: self.youtube_signals.get_technology_trends()

            youtube_result = self._safe_provider_call(
                "YouTube",
                youtube_callable or (lambda: []),
            )
            skills = youtube_result["skills"]
            # Use fallback when the API call fails
            if youtube_result["status"] != "ok" and hasattr(self.youtube_signals, "_get_fallback_skills"):
                skills = self.youtube_signals._get_fallback_skills()
            added = 0
            for skill in skills:
                cleaned = str(skill).strip().lower()
                if cleaned and cleaned not in emerging:
                    emerging[cleaned] = {"source": "youtube", "confidence": 0.65}
                    added += 1
            self._update_source_health("youtube", "ok" if added else "empty", count=added)
            self._last_source_trends["youtube"] = [
                skill for skill, detail in emerging.items() if detail.get("source") == "youtube"
            ]
        else:
            self._update_source_health("youtube", "unavailable", detail="YouTube source not configured")
            self._last_source_trends["youtube"] = []

        # 5. Google Trends
        if self.google_trends:
            google_result = self._safe_provider_call("Google Trends", self.google_trends.get_trending_skills)
            skills = google_result["skills"]
            if google_result["status"] != "ok":
                skills = [k.lower() for k in self.tech_keywords if k.strip()][:50]
            added = 0
            for skill in skills:
                cleaned = str(skill).strip().lower()
                if cleaned and cleaned not in emerging:
                    emerging[cleaned] = {"source": "google", "confidence": 0.8}
                    added += 1
            self._update_source_health("google", "ok" if added else "empty", count=added)
            self._last_source_trends["google"] = [
                skill for skill, detail in emerging.items() if detail.get("source") == "google"
            ]
        else:
            self._update_source_health("google", "unavailable", detail="Google Trends source not configured")
            for skill in self.tech_keywords[:30]:
                cleaned = str(skill).strip().lower()
                if cleaned and cleaned not in emerging:
                    emerging[cleaned] = {"source": "google-fallback", "confidence": 0.7}
            self._last_source_trends["google"] = [
                skill for skill, detail in emerging.items() if "google" in detail.get("source", "")
            ]

        # 6. Public Job-Market Signals (role-driven)
        if self.job_market_signals:
            role_for_market = active_role or (active_keywords[0] if active_keywords else "")
            market_result = self._safe_provider_call(
                "Job Market",
                lambda: self.job_market_signals.get_role_market_skills(role=role_for_market, keywords=active_keywords),
            )
            skills = market_result["skills"]
            added = 0
            for skill in skills:
                cleaned = str(skill).strip().lower()
                if cleaned and cleaned not in emerging:
                    emerging[cleaned] = {"source": "job_market", "confidence": 0.88}
                    added += 1

            # Keep statuses aligned with existing UI/tests expectations.
            status = "ok" if added else "empty"
            detail = "" if market_result["status"] == "ok" else market_result["detail"]
            self._update_source_health("job_market", status, count=added, detail=detail)
            self._last_source_trends["job_market"] = [
                skill for skill, detail in emerging.items() if detail.get("source") == "job_market"
            ]
        else:
            self._update_source_health("job_market", "unavailable", detail="Job market source not configured")
            self._last_source_trends["job_market"] = []

        return emerging

    def classify_skill_lifecycle(self, skill_details: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        lifecycle: Dict[str, Dict[str, Any]] = {}

        google_lifecycle = {}
        if self.google_trends and skill_details:
            try:
                if hasattr(self.google_trends, "get_skill_lifecycle"):
                    google_lifecycle = self.google_trends.get_skill_lifecycle(list(skill_details.keys()))
            except Exception as exc:
                logger.debug("Google lifecycle lookup failed: %s", exc)

        for skill, details in skill_details.items():
            source = details.get("source", "")
            confidence = float(details.get("confidence", 0.0))
            lifecycle_score = float(details.get("lifecycle_score", 0.0))
            google_state = google_lifecycle.get(skill, {}) if isinstance(google_lifecycle, dict) else {}

            # Determine status with priority: google real data > lifecycle_score > confidence > source defaults
            status = google_state.get("status")
            has_real_google_data = isinstance(google_state, dict) and google_state.get("average_score", 0) > 0
            
            if not status or (status and has_real_google_data is False):
                # Use lifecycle_score if available (from role-trending)
                if lifecycle_score >= 0.8:
                    status = "trending"
                elif lifecycle_score >= 0.6:
                    status = "emerging"
                elif lifecycle_score < 0.4:
                    status = "vanishing"
                elif source in {"google", "github", "youtube", "google-fallback", "role-trending"}:
                    status = "trending"
                elif source in {"esco", "onet", "job_market"} and confidence >= 0.9:
                    status = "stable"
                elif confidence < 0.5:
                    status = "vanishing"
                else:
                    status = "stable"

            lifecycle[skill] = {
                "status": status,
                "source": source,
                "confidence": round(confidence, 3),
            }
            if lifecycle_score:
                lifecycle[skill]["lifecycle_score"] = lifecycle_score
            if google_state:
                lifecycle[skill]["google"] = google_state

        return lifecycle

    def compute_market_gaps(self, current_skills: List[str], emerging_skills: List[str], max_market_gaps: int) -> List[str]:
        """Filter emerging skills to only those NOT in current_skills, using fuzzy matching."""
        from difflib import SequenceMatcher

        def extract_base_skill(skill_str: str) -> str:
            s = str(skill_str).strip().lower()
            if '(' in s and ')' in s:
                s = s[:s.index('(')].strip()
            return s

        def skills_equivalent(emerging: str, current: str) -> bool:
            e_base = extract_base_skill(emerging)
            c_base = extract_base_skill(current)
            if e_base == c_base:
                return True
            ratio = SequenceMatcher(None, e_base, c_base).ratio()
            return ratio > 0.85

        current_normalized = [extract_base_skill(s) for s in current_skills if str(s).strip()]
        gaps = []

        for emerging in emerging_skills:
            is_gap = True
            for current in current_normalized:
                if skills_equivalent(emerging, current):
                    is_gap = False
                    break
            if is_gap:
                gaps.append(emerging)

        return gaps[: max(1, max_market_gaps)]

    def collect_emerging_skills_fast(self, keywords: List[str] | None = None) -> Dict[str, Dict[str, Any]]:
        return self.collect_emerging_skills(keywords)