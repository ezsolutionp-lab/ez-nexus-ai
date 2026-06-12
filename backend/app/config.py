"""
EZ-NEXUS AI — Settings Module
Reads environment variables with sensible defaults.
Loaded once at startup; all modules import `settings`.
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # App
    app_name: str = "EZ-NEXUS AI Platform"
    base_url: str = "http://localhost:8000"
    secret_key: str = "change-this-to-a-long-random-string-in-production"

    # Database
    database_url: str = "sqlite:///./ez_nexus.db"

    # Anthropic / Claude
    anthropic_api_key: Optional[str] = None

    # Twilio — Real Phone Calls
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_phone_number: Optional[str] = None
    twilio_twiml_app_sid: Optional[str] = None

    # SMTP — Email Confirmations
    smtp_host: Optional[str] = None
    smtp_port: int = 465
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None

    # JWT Auth
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 hours

    # Default admin seed (change password after first login!)
    default_admin_email: str = "ez.nexusai@gmail.com"
    default_admin_password: str = "Commander@2024!"

    @property
    def twilio_configured(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_phone_number)

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
