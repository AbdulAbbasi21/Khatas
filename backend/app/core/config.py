"""App settings from environment variables / backend/.env."""

import os
from dataclasses import dataclass, field
from decimal import Decimal

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://khataz:khataz_dev@localhost:5432/khataz"
    )
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-only-secret-change-me-in-production-0123456789")
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))
    cors_origins: list[str] = field(
        default_factory=lambda: _list("CORS_ORIGINS", "http://localhost:5173")
    )
    storage_dir: str = os.getenv("STORAGE_DIR", "storage")
    max_upload_mb: float = float(os.getenv("MAX_UPLOAD_MB", "10"))
    scanner_enabled: bool = _bool("SCANNER_ENABLED", True)
    # received amount must be at least this share of the claimed amount (in USD terms)
    # the other side of a shared record can cancel an entry for this long; after that it's final
    # Khataz accounts whose PayPal is the PayPal app's own Business account: they use the app keys
    # above (PAYPAL_CLIENT_ID / SECRET), so their automatic payment check is always on
    paypal_receiver_emails: tuple[str, ...] = tuple(e.strip().lower() for e in
                                                    os.getenv("PAYPAL_RECEIVER_EMAILS", "").split(",") if e.strip())
    # optional smarter search; empty = the basic database search
    elastic_url: str = os.getenv("ELASTIC_URL", "")
    entry_cancel_hours: int = int(os.getenv("ENTRY_CANCEL_HOURS", "24"))
    payment_tolerance: Decimal = Decimal(os.getenv("PAYMENT_TOLERANCE", "0.95"))
    fx_timeout_seconds: float = float(os.getenv("FX_TIMEOUT_SECONDS", "6"))
    # where the web app runs (used for links in emails)
    app_url: str = os.getenv("APP_URL", "http://localhost:5173").rstrip("/")
    # email: leave SMTP_HOST empty to print emails in the terminal instead of sending
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_security: str = os.getenv("SMTP_SECURITY", "starttls").lower()  # starttls | ssl | none
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", os.getenv("SMTP_USER", ""))
    # PayPal: "Log in with PayPal" (verified sender) and automatic payment checks.
    # Leave the client ID empty to turn both off.
    paypal_env: str = os.getenv("PAYPAL_ENV", "sandbox").lower()  # sandbox | live
    paypal_client_id: str = os.getenv("PAYPAL_CLIENT_ID", "")
    paypal_client_secret: str = os.getenv("PAYPAL_CLIENT_SECRET", "")
    paypal_redirect_uri: str = os.getenv(
        "PAYPAL_REDIRECT_URI", os.getenv("APP_URL", "http://localhost:5173").rstrip("/") + "/paypal/callback")
    paypal_timeout_seconds: float = float(os.getenv("PAYPAL_TIMEOUT_SECONDS", "15"))
    # how often pending payments are checked against receivers' PayPal (0 = never in the background)
    paypal_sync_seconds: int = int(os.getenv("PAYPAL_SYNC_SECONDS", "120"))
    # "Type an entry": free AI providers, tried in order; built-in rules if none works
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    groq_stt_model: str = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")  # voice -> text
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "")  # any model id ending in :free
    ai_timeout_seconds: float = float(os.getenv("AI_TIMEOUT_SECONDS", "12"))


settings = Settings()
