"""Important notifications are also emailed (when SMTP is set up), only after the change is saved."""

import pytest

from app.core import email
from app.services import common
from tests.test_claims import claim


class SyncThread:
    def __init__(self, target, daemon=None):
        self.target = target

    def start(self):
        self.target()


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(email, "email_enabled", lambda: True)
    monkeypatch.setattr(email, "send_email", lambda to, subject, text, html=None: sent.append((to, subject, text)))
    monkeypatch.setattr(common.threading, "Thread", SyncThread)
    return sent


def test_receiver_is_emailed_about_a_payment(linked, outbox):
    abdul, marwan, rel_id = linked
    outbox.clear()
    assert claim(marwan, rel_id).status_code == 201
    assert len(outbox) == 1
    to, subject, text = outbox[0]
    assert to == "abdul@example.com" and subject.startswith("Khataz: Marwan Shahid sent you 30.00 USD")
    assert f"/records/{rel_id}" in text


def test_failed_requests_send_nothing_and_users_can_opt_out(linked, outbox):
    abdul, marwan, rel_id = linked
    outbox.clear()
    assert claim(marwan, rel_id, amount="-5").status_code == 422  # rejected: nothing saved, nothing sent
    assert outbox == []
    abdul.ok("patch", "/api/me", {"email_notifications": False})
    claim(marwan, rel_id)
    assert outbox == []
    assert abdul.ok("get", "/api/me")["email_notifications"] is False
