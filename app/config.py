"""Configuration and environment variables for Guardrail Arena."""
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    ENVIRONMENT: str = "development"
    
    # Private upstream credentials (strictly kept server-side)
    TYPESAFE_API_KEY: str = ""
    TYPESAFE_API_URL: str = "https://api.typesafe.ai/v1/systemone"
    
    # Engine weights / configuration
    LAYA_MODEL_PATH: str = "./weights/laya-base.bin"
    
    # Dataset location
    DATASET_PATH: str = "./data/flight_booking_metadata.parquet"
    
    # Security limits
    MAX_PROMPT_LENGTH: int = 4000
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
