from app.scanner.parser import looks_like_paypal, parse_receipt

APP_SCREENSHOT = """PayPal
You sent $25.00 USD to John Doe
Completed
Nov 3, 2026 at 10:15 AM
Paid with
Visa Credit ••••4417
Transaction ID
5TY05013RG002845M
Note
Rent share for November
"""

EMAIL_RECEIPT = """PayPal
Receipt for your payment
Hello Abdul,
You paid €49.99 EUR to Example Store
Merchant
Example Store
store@example.com
Transaction date
3 November 2026
Transaction ID: 8AB12345CD6789012
Status: Completed
Total €49.99 EUR
Fee €0.00 EUR
"""

RECEIVED = """PayPal
Sarah Khan sent you $120.50
Pending
11/02/2026
Transaction ID
9XK32109PL4567890
"""

NOT_PAYPAL = """SUPERMART
Milk 2.50
Bread 1.20
Total 3.70
Thank you for shopping
"""

def test_parser_cases():
    assert looks_like_paypal(APP_SCREENSHOT)["passed"]
    assert looks_like_paypal(EMAIL_RECEIPT)["passed"]
    assert looks_like_paypal(RECEIVED)["passed"]
    assert not looks_like_paypal(NOT_PAYPAL)["passed"]

    a = parse_receipt(APP_SCREENSHOT)
    assert a["transaction_id"] == "5TY05013RG002845M"
    assert a["amount"] == 25.0 and a["currency"] == "USD"
    assert a["direction"] == "sent" and a["counterparty"] == "John Doe"
    assert a["status"] == "Completed" and a["date"].startswith("Nov 3, 2026")

    e = parse_receipt(EMAIL_RECEIPT)
    assert e["transaction_id"] == "8AB12345CD6789012"
    assert e["amount"] == 49.99 and e["currency"] == "EUR" and e["fee"] == 0.0
    assert e["counterparty"] == "Example Store" and e["emails"] == ["store@example.com"]

    r = parse_receipt(RECEIVED)
    assert r["direction"] == "received" and r["counterparty"] == "Sarah Khan"
    assert r["amount"] == 120.5 and r["status"] == "Pending"


# --- issuer detection: merchant receipts that were only PAID via PayPal ------

# OCR of the "Prosper Remix" event receipt (merchant-issued, processed by PayPal)
MERCHANT_PROCESSED_BY_PAYPAL = """TRANSACTION RECEIPT
PROSPER
Prosper Remix
REMIX
August 17-18, 2021
Need assistance? Contact:
sarah.gough@emeraldx.com
Received:
Thursday, December 16,
First Name
2021
Shlomo
Last Name
Klein
Email
info@georgiewigs.com
Prosper Remix Registration Payment
Transaction ID
26E76470G41520719
Description
Amount
Event Registration
$199.00
$199.00 x 1
$199.00
This transaction has been processed by PayPal and will appear on your statement as PayPal
Prosper Remix
THANK YOU
"""

SHOP_PAID_WITH_PAYPAL = """ACME STORE
Order Confirmation
Order #10023
Payment method: PayPal
Transaction ID 7HJ12345KL6789012
Total $54.20 USD
Thank you for your order
"""

# PayPal app screenshot where OCR missed the logo (no word "PayPal" at all)
APP_NO_LOGO = """You sent $15.00 USD to Ali Raza
Completed
Oct 28, 2026 at 6:40 PM
Paid with
PayPal balance
Transaction ID
3KD84721MN0938475
Send again
"""

PAYPAL_EMAIL_PAID_WITH_BALANCE = """PayPal
Receipt for your payment
You paid $9.99 USD to Spotify
Paid with PayPal balance
Transaction ID: 1AB23456CD7890123
Total $9.99 USD
Help Center | paypal.com
"""


def test_merchant_receipt_processed_by_paypal_is_rejected():
    r = looks_like_paypal(MERCHANT_PROCESSED_BY_PAYPAL)
    assert r["passed"] is False
    assert r["issuer"] == "merchant_via_paypal"
    assert r["merchant"] == "Prosper Remix"


def test_shop_receipt_paid_with_paypal_is_rejected():
    r = looks_like_paypal(SHOP_PAID_WITH_PAYPAL)
    assert r["passed"] is False and r["issuer"] == "merchant_via_paypal"


def test_paypal_receipts_still_accepted():
    for text in (APP_SCREENSHOT, EMAIL_RECEIPT, RECEIVED, APP_NO_LOGO,
                 PAYPAL_EMAIL_PAID_WITH_BALANCE):
        r = looks_like_paypal(text)
        assert r["passed"] and r["issuer"] == "paypal", (text[:40], r)


def test_plain_receipt_not_paypal():
    assert looks_like_paypal(NOT_PAYPAL)["issuer"] == "not_paypal"
