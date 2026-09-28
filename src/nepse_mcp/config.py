from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    nepalipaisa_base_url: str = "https://nepalipaisa.com/api"
    nepse_http_timeout: int = 10
    log_level: str = "INFO"
    jevmodel_api_key: str | None = None
    jev_api_key: str | None = None
    typesafe_api_key: str | None = None
    jev_api_url: str = "https://jevmodel.org/v1/systemone"
    jev_model: str = "jev-latest"
    jev_confidence_threshold: float = 0.70
    jev_http_timeout: float = 30.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
