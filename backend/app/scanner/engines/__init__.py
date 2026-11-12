"""
ML engines (CLIP classifier + EasyOCR).

Heavy libraries are imported lazily so the rest of the app (and the tests)
work without torch installed. Each engine is a small class with one method,
which makes them easy to replace with fakes in tests or with a cloud OCR later.
"""

import threading

import numpy as np
from PIL import Image

from app.scanner.config import OTHER_LABELS, RECEIPT_LABELS, settings


class ClipClassifier:
    """Zero-shot: does the image look like a payment receipt?"""

    def __init__(self, model_name: str = settings.clip_model):
        from transformers import pipeline

        self._pipe = pipeline("zero-shot-image-classification", model=model_name)
        self._lock = threading.Lock()

    def classify(self, img: Image.Image) -> dict:
        with self._lock:
            preds = self._pipe(img, candidate_labels=RECEIPT_LABELS + OTHER_LABELS)
        receipt_score = sum(p["score"] for p in preds if p["label"] in RECEIPT_LABELS)
        return {
            "predicted": preds[0]["label"],
            "receipt_score": round(float(receipt_score), 3),
            "is_receipt": preds[0]["label"] in RECEIPT_LABELS
            and receipt_score >= settings.min_class_score,
        }


class EasyOcrEngine:
    """Returns text lines sorted top-to-bottom, left-to-right."""

    def __init__(self, languages=settings.ocr_languages, gpu: bool = settings.ocr_gpu):
        import easyocr

        self._reader = easyocr.Reader(languages, gpu=gpu)
        self._lock = threading.Lock()

    def read(self, gray: np.ndarray) -> list[dict]:
        with self._lock:
            results = self._reader.readtext(gray)
        # group boxes into rows (~15px bands), then left to right
        results.sort(key=lambda r: (round(r[0][0][1] / 15), r[0][0][0]))
        return [
            {"text": t, "confidence": round(float(c), 3)}
            for _, t, c in results
            if c >= settings.min_ocr_confidence
        ]


class Engines:
    def __init__(self, classifier=None, ocr=None):
        self.classifier = classifier
        self.ocr = ocr

    @classmethod
    def load(cls) -> "Engines":
        classifier = ClipClassifier() if settings.enable_classifier else None
        return cls(classifier=classifier, ocr=EasyOcrEngine())
