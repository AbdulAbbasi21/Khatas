"""The scan pipeline: bytes in -> ScanResponse out. No web framework code here."""

import io
import time

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from app.scanner.config import settings
from app.scanner.engines import Engines
from app.scanner.parser import looks_like_paypal, parse_receipt
from app.scanner.schemas import Checks, ReceiptData, ScanResponse

try:  # iPhone camera photos (HEIC)
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

REQUIRED_FIELDS = ("transaction_id", "amount", "date")


class InvalidImageError(ValueError):
    pass


def load_image(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)  # fix rotated phone photos
        return img.convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise InvalidImageError("File is not a supported image (use JPG, PNG, WEBP or HEIC)") from e


def quality(img: Image.Image) -> dict:
    w, h = img.size
    gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    problems = []
    if w < settings.min_width or h < settings.min_height:
        problems.append(f"Image is too small ({w}x{h}). Upload a larger screenshot.")
    if blur < settings.blur_threshold:
        problems.append("Image is too blurry to read. Retake the photo or upload a screenshot.")
    return {"ok": not problems, "width": w, "height": h, "blur": round(blur, 1), "problems": problems}


def preprocess_for_ocr(img: Image.Image) -> np.ndarray:
    gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    if gray.mean() < 110:  # dark-mode screenshot -> dark text on light background
        gray = 255 - gray
    longest = max(gray.shape)
    if longest < 1200:
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    elif longest > 3000:  # huge camera photos slow OCR down a lot
        scale = 3000 / longest
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return gray


def scan(data: bytes, engines: Engines) -> ScanResponse:
    start = time.perf_counter()
    ms = lambda: int((time.perf_counter() - start) * 1000)  # noqa: E731

    img = load_image(data)

    # 1. quality
    q = quality(img)
    checks = Checks(quality_ok=q["ok"], width=q["width"], height=q["height"], blur_score=q["blur"])
    if not q["ok"]:
        return ScanResponse(is_paypal_receipt=False, rejected_at="quality",
                            reason=" ".join(q["problems"]), confidence=0.0,
                            checks=checks, processing_ms=ms())

    # 2. does it look like a receipt?
    visual_score = None
    if engines.classifier is not None:
        c = engines.classifier.classify(img)
        visual_score = c["receipt_score"]
        checks.looks_like_receipt = c["is_receipt"]
        checks.visual_prediction = c["predicted"]
        checks.visual_score = visual_score
        if not c["is_receipt"]:
            return ScanResponse(is_paypal_receipt=False, rejected_at="classification",
                                reason="This image doesn't look like a payment receipt.",
                                confidence=round(1 - visual_score, 3),
                                checks=checks, processing_ms=ms())

    # 3. OCR
    lines = engines.ocr.read(preprocess_for_ocr(img))
    text = "\n".join(l["text"] for l in lines)
    raw_text = text if settings.return_raw_text else None

    # 4. is it PayPal?
    pp = looks_like_paypal(text, settings.min_keyword_hits)
    checks.issuer = pp["issuer"]
    checks.merchant = pp["merchant"]
    checks.mentions_paypal = pp["mentions_paypal"]
    checks.has_transaction_id = pp["has_transaction_id"]
    checks.keywords_found = pp["keywords_found"]
    if not pp["passed"]:
        if not text.strip():
            reason = "No readable text was found in the image."
        elif pp["issuer"] == "merchant_via_paypal":
            who = f" ({pp['merchant']})" if pp["merchant"] else ""
            reason = (f"This receipt was issued by a merchant{who}, not by PayPal. It only says "
                      "the payment went through PayPal. Upload the PayPal receipt instead: the "
                      "transaction screen in the PayPal app or the PayPal email receipt.")
        elif pp["issuer"] == "paypal":
            reason = "This looks like PayPal, but too little of the receipt could be read."
        else:
            reason = "This looks like a receipt, but not a PayPal one."
        return ScanResponse(is_paypal_receipt=False, rejected_at="paypal_check", reason=reason,
                            confidence=0.0, checks=checks, raw_text=raw_text, processing_ms=ms())

    # 5. extract
    fields = parse_receipt(text)
    missing = [f for f in REQUIRED_FIELDS if not fields.get(f)]

    # confidence: text evidence + found fields (+ visual score when available)
    conf = 0.35 * pp["mentions_paypal"] + 0.25 * pp["has_transaction_id"]
    conf += 0.10 * min(len(pp["keywords_found"]), 4) / 4
    conf += 0.30 * (len(REQUIRED_FIELDS) - len(missing)) / len(REQUIRED_FIELDS)
    if visual_score is not None:
        conf = 0.85 * conf + 0.15 * visual_score

    return ScanResponse(
        is_paypal_receipt=True,
        confidence=round(min(conf, 1.0), 3),
        complete=not missing,
        missing_fields=missing,
        reason=None if not missing else
        f"Some details couldn't be read ({', '.join(missing)}). A clearer screenshot may help.",
        receipt=ReceiptData(**fields),
        checks=checks,
        raw_text=raw_text,
        processing_ms=ms(),
    )
