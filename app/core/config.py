from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Automation Doctor"
    n8n_base_url: str = "http://localhost:5678"
    n8n_api_key: str | None = None
    n8n_timeout_seconds: float = 20.0
    allow_workflow_mutation: bool = False
    allow_execution_retry: bool = False
    operator_token: str | None = None
    max_patch_operations: int = 8
    state_db_path: str = "./data/ai-automation-doctor.db"
    remediation_lease_seconds: int = 30

    # AI diagnosis is advisory-only and disabled unless explicitly configured.
    ai_diagnosis_enabled: bool = False
    ai_api_base_url: str | None = None
    ai_api_key: str | None = None
    ai_model: str | None = None
    ai_timeout_seconds: float = 20.0
    ai_baseline_confidence_threshold: float = 0.80

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
