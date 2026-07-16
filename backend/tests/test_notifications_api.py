"""In-app notification read side (spec §7, §10 Channel 1).

A notification is addressed to one user; these endpoints only ever touch the
caller's own rows. The write side is covered where the fan-out happens
(test_publish_api).
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.models import Notification
from tests.factories import PASSWORD, create_user


def login(client: TestClient, username: str) -> None:
    resp = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


def _note(session: DbSession, user_id: int, event: str = "schedule_published") -> Notification:
    row = Notification(user_id=user_id, event_type=event, payload={"week": "2026-07-13"})
    session.add(row)
    session.commit()
    return row


def test_notifications_require_auth(client: TestClient) -> None:
    assert client.get("/notifications").status_code == 401
    assert client.post("/notifications/read", json={}).status_code == 401


def test_lists_only_own_notifications(client: TestClient, session: DbSession) -> None:
    pasha = create_user(session, "pasha")
    amir = create_user(session, "amir")
    _note(session, pasha.id, "schedule_published")
    _note(session, amir.id, "swap_requested")

    login(client, "pasha")
    body = client.get("/notifications").json()
    assert [n["event_type"] for n in body] == ["schedule_published"]
    assert all("is_root" not in n for n in body)


def test_mark_all_read(client: TestClient, session: DbSession) -> None:
    pasha = create_user(session, "pasha")
    _note(session, pasha.id)
    _note(session, pasha.id)

    login(client, "pasha")
    assert client.post("/notifications/read", json={}).status_code == 204
    rows = session.scalars(select(Notification).where(Notification.user_id == pasha.id)).all()
    assert all(n.read for n in rows)


def test_mark_specific_ids_read(client: TestClient, session: DbSession) -> None:
    pasha = create_user(session, "pasha")
    a = _note(session, pasha.id)
    b = _note(session, pasha.id)

    login(client, "pasha")
    client.post("/notifications/read", json={"ids": [a.id]})
    session.expire_all()
    assert session.get(Notification, a.id).read is True
    assert session.get(Notification, b.id).read is False


def test_cannot_mark_another_users_notification_read(
    client: TestClient, session: DbSession
) -> None:
    """The user_id predicate makes another user's id a silent no-op, not a write."""
    create_user(session, "pasha")
    amir = create_user(session, "amir")
    other = _note(session, amir.id)

    login(client, "pasha")
    client.post("/notifications/read", json={"ids": [other.id]})
    session.expire_all()
    assert session.get(Notification, other.id).read is False  # untouched
