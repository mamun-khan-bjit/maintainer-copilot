from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    github_token: str
    target_repo: str = "pydantic/pydantic"


settings = Settings()
