import json
from pathlib import Path
from typing import Dict, List

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.services.dynamic_defaults import (
    default_education_keywords,
    default_esco_role_skill_map,
    default_market_keywords,
    default_onet_occupation_skill_map,
    default_onet_trending_skills,
    default_role_keywords,
    default_skill_catalog,
    default_youtube_keywords,
    parse_csv,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_env: str = "dev"
    app_name: str = "Learning & Development Platform"
    groq_api_key: str = ""
    youtube_api_key: str = ""
    github_token: str = ""
    onet_api_key: str = ""
    database_url: str = "postgresql://postgres:postgres@localhost:5432/learning_pathway"
    chroma_path: str = "./chroma_db"
    log_level: str = "INFO"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_workers: int = 1
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    session_secret: str = "siemens-workforce-intelligence-dev-secret"
    max_upload_mb: int = 5
    esco_cache_path: str = "./cache"
    skill_matrix_workbook_path: str = Field(
        default="Nextwork-Skill-Matrix3.0-Team 1.xlsx",
        validation_alias=AliasChoices("skill_matrix_workbook_path", "nextwork_workbook_path"),
    )

    default_role_title: str = "Software Developer"
    max_core_gaps: int = 100
    max_market_gaps: int = 5
    max_emerging_skills: int = 30
    max_talent_matches: int = 5
    github_trending_window_days: int = 365

    skill_catalog_csv: str = ",".join(default_skill_catalog())
    education_keywords_csv: str = ",".join(default_education_keywords())
    role_keywords_csv: str = ",".join(default_role_keywords())
    market_keywords_csv: str = ",".join(default_market_keywords())
    onet_trending_skills_csv: str = ",".join(default_onet_trending_skills())
    youtube_keywords_csv: str = ",".join(default_youtube_keywords())

    esco_role_skill_map_json: str = json.dumps(default_esco_role_skill_map())
    onet_occupation_skill_map_json: str = json.dumps(default_onet_occupation_skill_map())

    model_config = SettingsConfigDict(env_file=str(PROJECT_ROOT / ".env"))

    @property
    def skill_catalog(self) -> List[str]:
        return parse_csv(self.skill_catalog_csv)

    @property
    def education_keywords(self) -> List[str]:
        return parse_csv(self.education_keywords_csv)

    @property
    def role_keywords(self) -> List[str]:
        return parse_csv(self.role_keywords_csv)

    @property
    def market_keywords(self) -> List[str]:
        return parse_csv(self.market_keywords_csv)

    @property
    def onet_trending_skills(self) -> List[str]:
        return parse_csv(self.onet_trending_skills_csv)

    @property
    def youtube_keywords(self) -> List[str]:
        return parse_csv(self.youtube_keywords_csv)

    @property
    def esco_role_skill_map(self) -> Dict[str, List[str]]:
        return self._parse_json_map(self.esco_role_skill_map_json, default_esco_role_skill_map())

    @property
    def onet_occupation_skill_map(self) -> Dict[str, List[str]]:
        return self._parse_json_map(self.onet_occupation_skill_map_json, default_onet_occupation_skill_map())

    @staticmethod
    def _parse_json_map(raw: str, fallback: Dict[str, List[str]]) -> Dict[str, List[str]]:
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                return fallback
            normalized: Dict[str, List[str]] = {}
            for key, value in data.items():
                if not isinstance(key, str):
                    continue
                if isinstance(value, list):
                    normalized[key.strip().lower()] = [str(item).strip().lower() for item in value if str(item).strip()]
            return normalized or fallback
        except Exception:
            return fallback

settings = Settings()