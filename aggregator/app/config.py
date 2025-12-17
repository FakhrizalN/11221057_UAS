"""
Configuration module for the Aggregator service.
Loads settings from environment variables with sensible defaults.
"""
import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Database configuration
    database_url: str = "postgresql://loguser:logpass@localhost:5432/logdb"
    
    # Redis configuration
    redis_url: str = "redis://localhost:6379"
    
    # Worker configuration
    worker_count: int = 4
    
    # Logging
    log_level: str = "INFO"
    
    # Application
    app_name: str = "Pub-Sub Log Aggregator"
    app_version: str = "1.0.0"
    
    # Redis channel for pub-sub
    redis_channel: str = "events"
    
    # Batch processing
    batch_size: int = 100
    flush_interval_ms: int = 1000
    
    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
