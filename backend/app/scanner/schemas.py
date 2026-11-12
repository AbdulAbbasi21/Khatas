"""Response models - these are the JSON shapes your website / app receive."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ReceiptData(BaseModel):
    transaction_id: Optional[str] = Field(None, examples=["5TY05013RG002845M"])
    direction: Optional[Literal["sent", "received"]] = Field(None, examples=["sent"])
    counterparty: Optional[str] = Field(None, description="Who the money went to / came from",
                                        examples=["John Doe"])
    amount: Optional[float] = Field(None, examples=[25.0])
    currency: Optional[str] = Field(None, examples=["USD"])
    fee: Optional[float] = None
    date: Optional[str] = Field(None, examples=["Nov 3, 2026 at 10:15 AM"])
    status: Optional[str] = Field(None, examples=["Completed"])
    funding_source: Optional[str] = Field(None, examples=["Visa Credit ••••4417"])
    emails: Optional[list[str]] = None
    note: Optional[str] = None


class Checks(BaseModel):
    quality_ok: bool
    width: int
    height: int
    blur_score: float
    looks_like_receipt: Optional[bool] = Field(None, description="null if classifier disabled")
    visual_prediction: Optional[str] = None
    visual_score: Optional[float] = None
    issuer: Optional[Literal["paypal", "merchant_via_paypal", "not_paypal"]] = Field(
        None, description="Who issued the receipt. Only 'paypal' is accepted.")
    merchant: Optional[str] = Field(None, description="Merchant name, for merchant receipts")
    mentions_paypal: Optional[bool] = None
    has_transaction_id: Optional[bool] = None
    keywords_found: list[str] = []


class ScanResponse(BaseModel):
    is_paypal_receipt: bool
    rejected_at: Optional[Literal["quality", "classification", "paypal_check"]] = None
    reason: Optional[str] = Field(None, description="Human-readable reason, safe to show users")
    confidence: float = Field(..., ge=0, le=1)
    complete: bool = Field(False, description="True if transaction_id, amount and date were all found")
    missing_fields: list[str] = []
    receipt: Optional[ReceiptData] = None
    checks: Checks
    raw_text: Optional[str] = None
    processing_ms: int


class ErrorResponse(BaseModel):
    detail: str
