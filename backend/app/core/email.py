"""Sending email (invites). Configure SMTP in backend/.env.

Works with any SMTP provider, e.g. Gmail (smtp.gmail.com, port 587, an *app password*),
Brevo, Resend, Mailgun or SendGrid. If SMTP_HOST is empty, emails are not sent: they are
printed in the backend terminal instead, so you can still test the flow.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import settings

log = logging.getLogger("khataz.email")


def email_enabled() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def send_email(to: str, subject: str, text: str, html: str | None = None) -> bool:
    """True if the email was handed to the mail server. Never raises."""
    if not email_enabled():
        log.warning("Email not sent (SMTP not configured). To: %s | %s\n%s", to, subject, text)
        return False
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        ctx = ssl.create_default_context()
        if settings.smtp_security == "ssl" or settings.smtp_port == 465:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=ctx, timeout=15)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
            if settings.smtp_security != "none":  # "none" only for a local test mail server
                server.starttls(context=ctx)
        with server:
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        log.info("Email sent to %s: %s", to, subject)
        return True
    except (smtplib.SMTPException, OSError) as e:
        log.error("Email to %s failed: %s", to, e)
        return False
