"""Settings, read from environment variables (or a .env file)."""

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    # --- API
    api_key: str = os.getenv("API_KEY", "")  # empty = no auth (local dev)
    cors_origins: list[str] = field(default_factory=lambda: _list("CORS_ORIGINS", "*"))
    max_upload_mb: float = float(os.getenv("MAX_UPLOAD_MB", "10"))
    return_raw_text: bool = _bool("RETURN_RAW_TEXT", True)

    # --- Stage 1: image quality
    min_width: int = int(os.getenv("MIN_WIDTH", "250"))
    min_height: int = int(os.getenv("MIN_HEIGHT", "250"))
    blur_threshold: float = float(os.getenv("BLUR_THRESHOLD", "40"))

    # --- Stage 2: visual classifier (CLIP). Turn off for a lighter server.
    enable_classifier: bool = _bool("ENABLE_CLASSIFIER", True)
    clip_model: str = os.getenv("CLIP_MODEL", "openai/clip-vit-base-patch32")
    min_class_score: float = float(os.getenv("MIN_CLASS_SCORE", "0.40"))

    # --- Stage 3: OCR
    ocr_languages: list[str] = field(default_factory=lambda: _list("OCR_LANGUAGES", "en"))
    ocr_gpu: bool = _bool("OCR_GPU", False)
    min_ocr_confidence: float = float(os.getenv("MIN_OCR_CONFIDENCE", "0.30"))

    # --- Stage 4: PayPal text check
    min_keyword_hits: int = int(os.getenv("MIN_KEYWORD_HITS", "2"))


settings = Settings()

RECEIPT_LABELS = [
    "a screenshot of a payment confirmation in a mobile app",
    "a screenshot of an email payment receipt",
    "a photo of a payment receipt",
    "a screenshot of a bank transaction details page",
]
OTHER_LABELS = [
    "a photo of a person",
    "a photo of a landscape",
    "a photo of an animal",
    "a photo of food",
    "a screenshot of a chat conversation",
    "a screenshot of a social media post",
    "a photo of a handwritten note",
    "a meme",
    "a screenshot of a video game",
]
