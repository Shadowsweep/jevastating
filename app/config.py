import os
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class Settings(BaseSettings):
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    ENVIRONMENT: str = "development"
    
    # Private upstream credentials (strictly kept server-side)
    TYPESAFE_API_KEY: str = ""
    TYPESAFE_API_URL: str = "https://api.typesafe.ai/v1/systemone"
    
    # Engine weights / configuration
    LAYA_MODEL_PATH: str = os.path.join(BASE_DIR, "weights", "laya-base.bin")
    
    # Dataset locations
    FLIGHT_DATASET_PATH: str = os.path.join(BASE_DIR, "data", "flight_booking_metadata.parquet")
    DATASET_PATH: str = os.path.join(BASE_DIR, "data", "flight_booking_metadata.parquet")
    RAILWAY_DATASET_PATH: str = os.path.join(BASE_DIR, "data", "railway_tickets.parquet")
    CSV_DATASET_PATH: str = os.path.join(BASE_DIR, "data", "railway_tickets.csv")
    
    # Security limits
    MAX_PROMPT_LENGTH: int = 4000
    
    model_config = SettingsConfigDict(
        env_file=os.path.join(BASE_DIR, ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
