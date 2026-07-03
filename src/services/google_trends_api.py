import logging
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class GoogleTrendsAPI:
    """Google Trends API wrapper with retry logic and caching.
    
    Note: pytrends library has reliability issues with Google's anti-scraping.
    This implementation adds retry logic and graceful fallback.
    """
    
    def __init__(self, keywords: Optional[List[str]] = None, hl: str = "en-US", tz: int = 360):
        self.keywords = keywords or ["AI", "machine learning", "Python", "cloud computing", "cybersecurity"]
        self.hl = hl
        self.tz = tz
        self.pytrends = None
        self._cache = {}  # Simple cache: keyword -> (timestamp, results)
        self._cache_ttl = 3600  # 1 hour cache TTL
        self.max_retries = 1
        self.retry_delay = 0  # seconds
        self._max_keyword_batch = 5
        self._region_probes = ["united_states", "india", "united_kingdom"]
        
        try:
            from pytrends.request import TrendReq
            self.pytrends = TrendReq(hl=hl, tz=tz, retries=2, backoff_factor=0.3)
            logger.info("Google Trends API initialized with retry support")
        except ImportError:
            self.pytrends = None
            logger.warning("pytrends not installed - Google Trends disabled")
        except Exception as e:
            self.pytrends = None
            logger.warning(f"Failed to initialize Google Trends: {e}")

    @staticmethod
    def _normalize_term(term: Any) -> str:
        normalized = " ".join(str(term).lower().strip().split())
        normalized = re.sub(r"[^a-z0-9+.#\-/ ]", "", normalized)
        return normalized[:120]

    def _cache_get(self, cache_key: str):
        if cache_key in self._cache:
            timestamp, cached_results = self._cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return cached_results
        return None

    def _cache_set(self, cache_key: str, value: Any):
        self._cache[cache_key] = (time.time(), value)

    def _collect_interest_scores(self, terms: List[str], timeframe: str = "today 12-m") -> Dict[str, Dict[str, float]]:
        """Collect average/recent interest scores in small batches to reduce pytrends failures."""
        if not self.pytrends:
            return {}

        metrics: Dict[str, Dict[str, float]] = {}
        normalized_terms = [self._normalize_term(term) for term in terms]
        normalized_terms = [term for term in normalized_terms if term]
        if not normalized_terms:
            return metrics

        for start in range(0, len(normalized_terms), self._max_keyword_batch):
            batch = normalized_terms[start : start + self._max_keyword_batch]
            if not batch:
                continue

            for attempt in range(self.max_retries):
                try:
                    self.pytrends.build_payload(batch, timeframe=timeframe)
                    trends = self.pytrends.interest_over_time()
                    if trends is None or trends.empty:
                        break

                    for col in trends.columns:
                        if str(col).lower() == "ispartial":
                            continue
                        series = trends[col].dropna()
                        if series.empty:
                            continue
                        values = [float(v) for v in series.tolist()]
                        if not values:
                            continue
                        avg_score = sum(values) / len(values)
                        recent_window = values[-3:] if len(values) >= 3 else values
                        recent_score = sum(recent_window) / len(recent_window)
                        name = self._normalize_term(col)
                        if not name:
                            continue
                        existing = metrics.get(name)
                        if existing is None or recent_score > existing.get("recent", 0.0):
                            metrics[name] = {
                                "average": round(avg_score, 2),
                                "recent": round(recent_score, 2),
                            }
                    break
                except Exception as e:
                    is_last_attempt = attempt == self.max_retries - 1
                    if is_last_attempt:
                        logger.debug(f"Google Trends batch failed for {batch}: {e}")
                    else:
                        time.sleep(self.retry_delay)
        return metrics

    def _collect_related_terms(self, seeds: List[str]) -> List[str]:
        """Use related queries to discover additional, currently rising topics."""
        if not self.pytrends:
            return []

        results: List[str] = []
        for seed in seeds:
            seed_clean = self._normalize_term(seed)
            if not seed_clean:
                continue
            for attempt in range(self.max_retries):
                try:
                    self.pytrends.build_payload([seed_clean], timeframe="today 12-m")
                    related = self.pytrends.related_queries() or {}
                    seed_related = related.get(seed_clean, {}) if isinstance(related, dict) else {}
                    for key in ("rising", "top"):
                        frame = seed_related.get(key)
                        if frame is None or frame.empty:
                            continue
                        query_col = frame.get("query")
                        if query_col is None:
                            continue
                        for query in query_col.head(10).tolist():
                            term = self._normalize_term(query)
                            if term:
                                results.append(term)
                    break
                except Exception as e:
                    is_last_attempt = attempt == self.max_retries - 1
                    if is_last_attempt:
                        logger.debug(f"Related queries failed for '{seed_clean}': {e}")
                    else:
                        time.sleep(self.retry_delay)
        return results

    def _collect_trending_search_terms(self) -> List[str]:
        """Get region-wise trending searches as an additional signal."""
        if not self.pytrends:
            return []

        terms: List[str] = []
        for region in self._region_probes:
            for attempt in range(self.max_retries):
                try:
                    frame = self.pytrends.trending_searches(pn=region)
                    if frame is not None and not frame.empty:
                        first_col = frame.columns[0]
                        for query in frame[first_col].head(20).tolist():
                            term = self._normalize_term(query)
                            if term:
                                terms.append(term)
                    break
                except Exception as e:
                    is_last_attempt = attempt == self.max_retries - 1
                    if is_last_attempt:
                        logger.debug(f"Trending searches probe failed for {region}: {e}")
                    else:
                        time.sleep(self.retry_delay)
        return terms

    def get_trending_skills(self, category: str = "technology") -> List[str]:
        """Get trending skills with retry, multi-signal scoring, and graceful fallback."""
        cache_key = f"trends_{category}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.debug(f"Returning cached Google Trends results ({len(cached)} items)")
            return cached

        if not self.pytrends:
            # Degrade gracefully if pytrends is unavailable.
            fallback = [self._normalize_term(k) for k in self.keywords if self._normalize_term(k)]
            self._cache_set(cache_key, fallback)
            logger.debug("Google Trends not initialized; returning normalized keywords as fallback")
            return fallback

        base_metrics = self._collect_interest_scores(self.keywords)
        related_terms = self._collect_related_terms(self.keywords)
        region_terms = self._collect_trending_search_terms()

        score_map: Dict[str, float] = {}
        for term, values in base_metrics.items():
            avg_score = float(values.get("average", 0.0))
            recent_score = float(values.get("recent", 0.0))
            momentum = max(0.0, recent_score - avg_score)
            score_map[term] = score_map.get(term, 0.0) + recent_score + (0.8 * momentum)

        for term in related_terms:
            score_map[term] = score_map.get(term, 0.0) + 30.0
        for term in region_terms:
            score_map[term] = score_map.get(term, 0.0) + 20.0

        if score_map:
            ranked = sorted(score_map.items(), key=lambda item: item[1], reverse=True)
            results = [term for term, _ in ranked][:50]
            self._cache_set(cache_key, results)
            logger.info(f"Google Trends success: {len(results)} terms aggregated")
            return results

        stale = self._cache.get(cache_key)
        if stale is not None:
            _, stale_value = stale
            logger.debug(f"Google Trends empty live result; using stale cache ({len(stale_value)} items)")
            return stale_value

        fallback = [self._normalize_term(k) for k in self.keywords if self._normalize_term(k)]
        self._cache_set(cache_key, fallback)
        logger.debug("Google Trends empty live result; returning keyword fallback")
        return fallback

    def get_skill_lifecycle(self, skills: List[str]) -> Dict[str, Dict[str, float | str]]:
        """Classify skills as trending, stable, or vanishing using 12-month momentum."""
        normalized_skills = [self._normalize_term(skill) for skill in skills]
        normalized_skills = [skill for skill in normalized_skills if skill]
        if not normalized_skills:
            return {}

        cache_key = "lifecycle_" + "|".join(sorted(set(normalized_skills)))
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        metrics = self._collect_interest_scores(normalized_skills)
        lifecycle: Dict[str, Dict[str, float | str]] = {}
        for skill in normalized_skills:
            values = metrics.get(skill, {"average": 0.0, "recent": 0.0})
            average = float(values.get("average", 0.0))
            recent = float(values.get("recent", 0.0))

            if average <= 0:
                status = "stable"
                delta_pct = 0.0
            else:
                delta_pct = ((recent - average) / average) * 100.0
                if recent >= 15 and delta_pct >= 15:
                    status = "trending"
                elif recent < 20 and delta_pct <= -25:
                    status = "vanishing"
                else:
                    status = "stable"

            lifecycle[skill] = {
                "status": status,
                "average_score": round(average, 2),
                "recent_score": round(recent, 2),
                "trend_delta_percent": round(delta_pct, 2),
            }

        self._cache_set(cache_key, lifecycle)
        return lifecycle

    def get_skill_trends(self, skill: str) -> List[str]:
        """Get trends for a specific skill with retry logic.
        
        Returns list with skill if trending, empty list if not.
        """
        skill_clean = self._normalize_term(skill)
        if not skill_clean:
            return []

        lifecycle = self.get_skill_lifecycle([skill_clean])
        status = lifecycle.get(skill_clean, {}).get("status", "stable")
        if status == "vanishing":
            return []
        return [skill_clean]

    def clear_cache(self):
        """Clear the trends cache."""
        self._cache.clear()
        logger.debug("Google Trends cache cleared")
