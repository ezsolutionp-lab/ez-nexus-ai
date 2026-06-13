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
    environment: str = "development"
    base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:5173"
    secret_key: str = "change-this-to-a-long-random-string-in-production"

    # Database
    database_url: str = "sqlite:///./ez_nexus.db"

    # Anthropic / Claude
    anthropic_api_key: Optional[str] = None

    # OpenAI fallback
    openai_api_key: Optional[str] = None
    default_ai_provider: str = "anthropic"   # anthropic | openai

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
    smtp_from: str = "EZ-NEXUS AI <no-reply@ez-nexus-ai.com>"

    # JWT Auth
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 hours

    # Default admin seed (change password after first login!)
    default_admin_email: str = "ez.nexusai@gmail.com"
    default_admin_password: str = "Commander@2024!"

    # Document processing & OCR
    enable_ocr: bool = True
    ocr_engine: str = "tesseract"   # tesseract | cloud
    max_upload_mb: int = 25
    upload_dir: str = "./uploads"   # relative to backend working directory

    # Compliance & safety
    require_admin_approval: bool = True
    phi_mode: bool = True             # HIPAA-mode: extra caution on patient data
    audit_log_enabled: bool = True
    allow_auto_production_upgrades: bool = False   # Commander can NEVER deploy without admin approval

    @property
    def twilio_configured(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_phone_number)

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password)

    @property
    def ai_configured(self) -> bool:
        return bool(self.anthropic_api_key or self.openai_api_key)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
