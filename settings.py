"""
Application settings using pydantic-settings.
Automatically loads from .env file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Google Cloud Vision API (required)
    google_credentials_file: str

    # Santa Monica account details (required)
    account_number: str
    zip_code: str
    last_name: str
    email: str

    # Printer configuration (optional)
    printer_ip: str | None = None
    printer_name: str = "AutoPrinter"
    auto_print: bool = True

    # Mode configuration
    dry_run: bool = True


# Global settings instance
settings = Settings()
