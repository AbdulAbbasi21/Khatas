from app.services.claims import parse_local_datetime, same_party

TXN = "5TY05013RG002845M"


def receipt(api, rel_id, seed):
    """Upload a small, unique PNG through the scan step and return its hash."""
    from io import BytesIO
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    meta = PngInfo()
    meta.add_text("seed", seed)  # makes every test image's bytes unique
    buf = BytesIO()
    Image.new("RGB", (8, 8), (0, 112, 186)).save(buf, "PNG", pnginfo=meta)
    r = api.post(f"/api/relationships/{rel_id}/claims/scan",
                 files={"file": (f"{seed}.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    return r.json()["image_hash"]


def claim(api, rel_id, amount="30.00", currency="USD", txn=TXN, image=True, **extra):
    body = {"amount": amount, "currency": currency, "sender_txn_id": txn,
            "paid_at_local": "2026-11-03T10:15:00", **extra}
    if image and "image_hash" not in body:
        try:
            body["image_hash"] = receipt(api, rel_id, f"{txn}-{amount}-{currency}-{sorted(extra.items())}")
        except AssertionError:
            pass  # scan refused (e.g. recipient not on Khataz); let the claim call report it
    return api.post(f"/api/relationships/{rel_id}/claims", body)


def bal(api, rel_id):
    return api.ok("get", f"/api/relationships/{rel_id}")["totals"]["balance"]


def test_confirmed_claim_reduces_balance_once(linked):
    abdul, marwan, rel_id = linked
    r = claim(marwan, rel_id)
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["state"] == "pending_confirmation" and c["recipient_user_id"] == abdul.user["id"]
    assert bal(abdul, rel_id) == "100.00"  # nothing changes before confirmation
    # paid_at was typed in Marwan's London time -> stored as UTC
    assert c["paid_at"] == "2026-11-03T10:15:00Z"
    assert abdul.ok("get", "/api/dashboard")["counts"]["to_confirm"] == 1

    assert marwan.post(f"/api/claims/{c['id']}/respond", {"response": "received"}).status_code == 403
    done = abdul.ok("post", f"/api/claims/{c['id']}/respond", {"response": "received"})
    assert done["state"] == "allocated" and done["allocated_entry_id"]
    assert bal(abdul, rel_id) == "70.00" and bal(marwan, rel_id) == "70.00"

    # the same payment can't be claimed again
    again = claim(marwan, rel_id)
    assert again.status_code == 409 and "already submitted" in again.json()["detail"]
    assert abdul.post(f"/api/claims/{c['id']}/respond", {"response": "received"}).status_code == 409


def test_not_received_changes_nothing(linked):
    abdul, marwan, rel_id = linked
    c = claim(marwan, rel_id).json()
    r = abdul.ok("post", f"/api/claims/{c['id']}/respond", {"response": "not_received"})
    assert r["state"] == "disputed" and bal(abdul, rel_id) == "100.00"


def test_fees_within_tolerance_are_accepted(linked):
    abdul, marwan, rel_id = linked
    c = claim(marwan, rel_id, amount="30.00").json()
    r = abdul.ok("post", f"/api/claims/{c['id']}/respond",
                 {"response": "received", "received_amount": "28.80"})  # 96%
    assert r["state"] == "allocated"
    assert bal(abdul, rel_id) == "71.20"  # reduced by what actually arrived


def test_big_shortfall_goes_to_review_then_owner_decides(linked):
    abdul, marwan, rel_id = linked
    c = claim(marwan, rel_id, amount="30.00").json()
    r = abdul.ok("post", f"/api/claims/{c['id']}/respond",
                 {"response": "different_amount", "received_amount": "20.00"})
    assert r["state"] == "needs_review"
    assert set(r["review_reasons"]) >= {"different_amount", "amount_below_tolerance"}
    assert bal(abdul, rel_id) == "100.00"
    abdul.ok("post", f"/api/claims/{c['id']}/resolve", {"action": "hold", "note": "Asking Marwan"})
    r = abdul.ok("post", f"/api/claims/{c['id']}/resolve", {"action": "allocate", "note": "Agreed"})
    assert r["state"] == "allocated" and bal(abdul, rel_id) == "80.00"


def test_other_currency_is_converted_and_rate_saved(linked):
    abdul, marwan, rel_id = linked
    c = claim(marwan, rel_id, amount="25.00", currency="EUR").json()
    r = abdul.ok("post", f"/api/claims/{c['id']}/respond", {"response": "received"})
    assert r["state"] == "allocated"
    assert r["converted_amount"] == "27.00" and r["fx_source"] == "test rates"
    assert bal(abdul, rel_id) == "73.00"


def test_third_party_payer_needs_owner_approval(linked):
    abdul, marwan, rel_id = linked
    c = claim(marwan, rel_id, payer_name="Faizan Ahmed").json()
    r = abdul.ok("post", f"/api/claims/{c['id']}/respond", {"response": "received"})
    assert r["state"] == "needs_review" and "payer_mismatch" in r["review_reasons"]
    review = abdul.ok("get", "/api/review")
    assert review["to_review"][0]["claim"]["id"] == c["id"]
    abdul.ok("post", f"/api/claims/{c['id']}/resolve", {"action": "allocate", "note": "Faizan paid for Marwan"})
    assert bal(abdul, rel_id) == "70.00"


def test_payment_to_someone_else_is_flagged(linked):
    abdul, marwan, rel_id = linked
    c = claim(marwan, rel_id, payee_name="Prosper Remix").json()
    r = abdul.ok("post", f"/api/claims/{c['id']}/respond", {"response": "received"})
    assert "payee_mismatch" in r["review_reasons"]
    r = abdul.ok("post", f"/api/claims/{c['id']}/resolve", {"action": "reject", "note": "Not my account"})
    assert r["state"] == "rejected" and bal(abdul, rel_id) == "100.00"


def test_overpayment_and_pending_status_flagged(linked):
    abdul, marwan, rel_id = linked
    c = claim(marwan, rel_id, amount="150.00", paypal_status="Pending").json()
    r = abdul.ok("post", f"/api/claims/{c['id']}/respond", {"response": "received"})
    assert {"overpayment", "paypal_status_not_completed"} <= set(r["review_reasons"])


def test_refund_reverses_allocated_payment(linked):
    abdul, marwan, rel_id = linked
    c = claim(marwan, rel_id).json()
    abdul.ok("post", f"/api/claims/{c['id']}/respond", {"response": "received"})
    assert bal(abdul, rel_id) == "70.00"
    r = abdul.ok("post", f"/api/claims/{c['id']}/reverse", {"reason": "PayPal chargeback"})
    assert r["state"] == "reversed" and bal(abdul, rel_id) == "100.00"


def test_claims_need_a_recipient_on_khataz(make_user):
    u = make_user("o@example.com", "O")
    b = u.ok("post", "/api/businesses", {"name": "Shop"}, 201)
    rel = u.ok("post", f"/api/businesses/{b['id']}/contacts", {"name": "Supplier", "side": "payable", "local_id": "T003"}, 201)
    r = claim(u, rel["id"])
    assert r.status_code == 400 and "isn't on Khataz" in r.json()["detail"]


def test_owner_can_log_screenshot_for_unlinked_customer(make_user):
    u = make_user("o@example.com", "Owner Name")
    b = u.ok("post", "/api/businesses", {"name": "Shop"}, 201)
    rel = u.ok("post", f"/api/businesses/{b['id']}/contacts", {"name": "Walk-in Ali", "side": "receivable", "local_id": "T004"}, 201)
    u.ok("post", f"/api/relationships/{rel['id']}/entries", {"type": "credit", "amount": "40"}, 201)
    c = claim(u, rel["id"], amount="40.00")
    assert c.status_code == 201 and c.json()["recipient_user_id"] == u.user["id"]
    u.ok("post", f"/api/claims/{c.json()['id']}/respond", {"response": "received"})
    assert bal(u, rel["id"]) == "0.00"


def test_bad_transaction_id_rejected(linked):
    abdul, marwan, rel_id = linked
    assert claim(marwan, rel_id, txn="123").status_code == 400


def test_helpers():
    assert parse_local_datetime("Nov 3, 2026 at 10:15 AM") == "2026-11-03T10:15"
    assert parse_local_datetime("3 November 2026") == "2026-11-03T00:00"
    assert parse_local_datetime("garbage") is None
    assert same_party("Marwan", "Marwan Shahid")
    assert same_party("marwan@example.com", "Marwan Shahid", "marwan@example.com")
    assert not same_party("Faizan Ahmed", "Marwan Shahid", "marwan@example.com")


def test_claim_needs_the_receipt(linked):
    abdul, marwan, rel_id = linked
    r = claim(marwan, rel_id, image=False)
    assert r.status_code == 400 and "receipt" in r.json()["detail"]


def test_non_paypal_receipt_is_refused(linked):
    from app.services import claims as svc
    abdul, marwan, rel_id = linked
    h = receipt(marwan, rel_id, "merchant")
    svc._save_verdict(h, False, "Merchant receipt, not a PayPal receipt")
    r = claim(marwan, rel_id, image_hash=h)
    assert r.status_code == 400 and "Merchant" in r.json()["detail"]
