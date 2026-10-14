from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    github_token: str
    target_repo: str = "pydantic/pydantic"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen2.5:3b"

    # USD per 1M tokens. Copy from the provider's official pricing page and note the date you checked.
    llm_prices: dict[str, dict[str, float]] = {
        "qwen2.5:3b": {"input": 0.0, "output": 0.0},  # runs locally on Ollama
        # "<model-name>": {"input": ..., "output": ...},  # <provider pricing page URL>, checked YYYY-MM-DD
    }



settings = Settings()
