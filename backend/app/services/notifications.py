"""Notification abstraction with replaceable providers.

POC providers are mocks (log + persist). Production swaps in SES (email),
SNS / Pinpoint / Twilio (SMS) by implementing NotificationProvider.
Message bodies sent over email/SMS must stay PHI-minimal ("You have a new
message in the Recovery Companion app"), which the mock enforces too.
"""
from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.observability import log_event, metrics
from app.models import Notification, Patient, User

logger = logging.getLogger("notifications")


class NotificationProvider(ABC):
    channel: str
    name: str

    @abstractmethod
    def send(self, to: str, title: str, body: str) -> str:
        """Deliver and return a provider message id. Raise on failure."""


class MockEmailProvider(NotificationProvider):
    channel, name = "EMAIL", "mock-email"

    def send(self, to: str, title: str, body: str) -> str:
        log_event(logger, "mock email sent", to=to, subject=title)
        return f"mock-email-{uuid.uuid4().hex[:12]}"


class MockSmsProvider(NotificationProvider):
    channel, name = "SMS", "mock-sms"

    def send(self, to: str, title: str, body: str) -> str:
        log_event(logger, "mock sms sent", to=to)
        return f"mock-sms-{uuid.uuid4().hex[:12]}"


class InAppProvider(NotificationProvider):
    channel, name = "IN_APP", "in-app"

    def send(self, to: str, title: str, body: str) -> str:
        return f"in-app-{uuid.uuid4().hex[:12]}"


def _providers() -> dict[str, NotificationProvider]:
    s = get_settings()
    # Extension point: map "ses" / "sns" / "twilio" to real implementations.
    email = {"mock": MockEmailProvider()}.get(s.notification_email_provider, MockEmailProvider())
    sms = {"mock": MockSmsProvider()}.get(s.notification_sms_provider, MockSmsProvider())
    return {"EMAIL": email, "SMS": sms, "IN_APP": InAppProvider()}


EXTERNAL_SAFE_BODY = "You have a new update in your Recovery Companion app. Please sign in to view it."


def notify(db: Session, *, category: str, title: str, body: str, user: User | None = None,
           patient: Patient | None = None, channels: tuple[str, ...] = ("IN_APP",),
           dedupe_key: str | None = None) -> list[Notification]:
    providers = _providers()
    created: list[Notification] = []
    for channel in channels:
        to = (user.email if user else None) if channel == "EMAIL" else (
            (patient.phone if patient else None) or (user.phone if user else None)) if channel == "SMS" else "app"
        n = Notification(
            user_id=user.id if user else None, patient_id=patient.id if patient else None, channel=channel,
            category=category, title=title, body=body if channel == "IN_APP" else EXTERNAL_SAFE_BODY,
            provider=providers[channel].name,
            dedupe_key=f"{dedupe_key}:{channel}" if dedupe_key else None,
        )
        try:
            with db.begin_nested():
                db.add(n)
                db.flush()
        except IntegrityError:
            continue  # already sent (dedupe)
        try:
            n.provider_message_id = providers[channel].send(to or "unknown", n.title, n.body)
            n.status = "SENT"
            n.sent_at = datetime.now(timezone.utc)
        except Exception as exc:  # provider failure must not break the clinical workflow
            n.status = "FAILED"
            logger.warning("notification failed", extra={"extra_fields": {"error": str(exc)}})
        metrics.inc("notifications", channel=channel, category=category, status=n.status)
        created.append(n)
    return created
