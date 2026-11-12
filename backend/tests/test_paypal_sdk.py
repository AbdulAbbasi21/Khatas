"""The PayPal Server SDK (APIMatic-generated) path, run against a local fake PayPal."""

import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from paypalserversdk.configuration import Configuration, Environment, Server

from app.services import paypal

GOOD = ("good-id", "good-secret")


def _rows(page):
    return [{"transaction_info": {"transaction_id": f"TX{page}{i}", "transaction_status": "S",
                                  "transaction_amount": {"currency_code": "USD", "value": "10.00"}},
             "payer_info": {"email_address": "faizan@personal.example.com"}} for i in range(2)]


class FakePayPal(BaseHTTPRequestHandler):
    calls: list = []
    search_status = 200

    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        import base64
        user = base64.b64decode(self.headers["Authorization"].split()[1]).decode()
        if tuple(user.split(":", 1)) != GOOD:
            return self._send(401, {"error": "invalid_client", "error_description": "Client Authentication failed"})
        self._send(200, {"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        FakePayPal.calls.append((u.path, q, self.headers.get("Authorization")))
        if FakePayPal.search_status != 200:
            return self._send(FakePayPal.search_status, {"name": "NOT_AUTHORIZED", "message": "nope"})
        page = int(q.get("page", 1))
        self._send(200, {"transaction_details": _rows(page), "page": page, "total_pages": 2})


@pytest.fixture
def fake_paypal(monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakePayPal)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    envs = {Environment.SANDBOX: {Server.DEFAULT: url}, Environment.PRODUCTION: {Server.DEFAULT: url}}
    monkeypatch.setattr(Configuration, "environments", envs)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    FakePayPal.calls, FakePayPal.search_status = [], 200
    yield
    srv.shutdown()


def test_sdk_reads_all_pages(fake_paypal):
    now = datetime.now(timezone.utc)
    rows = paypal.list_transactions(*GOOD, now - timedelta(days=90), now)
    assert [r["transaction_info"]["transaction_id"] for r in rows] == ["TX10", "TX11", "TX20", "TX21"]
    path, q, auth = FakePayPal.calls[0]
    assert path == "/v1/reporting/transactions" and auth == "Bearer tok"
    assert q["fields"] == "transaction_info,payer_info" and q["page_size"] == "100"
    start = datetime.strptime(q["start_date"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert now - start <= timedelta(days=31, seconds=5)  # PayPal's 31-day limit is respected


def test_sdk_bad_keys(fake_paypal):
    with pytest.raises(paypal.PayPalError, match="rejected the client ID"):
        paypal.check_credentials("wrong", "keys")


def test_sdk_search_not_enabled(fake_paypal):
    FakePayPal.search_status = 403
    with pytest.raises(paypal.PayPalError, match="turn on Transaction search"):
        paypal.check_credentials(*GOOD)
