from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Automation Doctor"
    n8n_base_url: str = "http://localhost:5678"
    n8n_api_key: str | None = None
    n8n_timeout_seconds: float = 20.0
    allow_workflow_mutation: bool = False
    allow_execution_retry: bool = False
    max_patch_operations: int = 8
    state_db_path: str = "./data/ai-automation-doctor.db"
    remediation_lease_seconds: int = 30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
