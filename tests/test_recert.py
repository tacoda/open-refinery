from datetime import datetime, timedelta

import pytest

from open_refinery import (
    SqliteSink,
    connect,
    create_user,
    Verdict,
    decide_item,
    emit_recert_overdue,
    open_campaign,
    overdue_campaigns,
    query_events,
    recert_progress,
)
from open_refinery.models import now_iso
from open_refinery.recert import list_items
from open_refinery.users import authenticate, set_active


def _conn(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    conn = connect("sqlite:///:memory:")
    admin, _ = create_user(conn, "admin@x.dev", "pw", "admin")
    return conn, admin


def test_campaign_snapshots_active_users(monkeypatch):
    conn, admin = _conn(monkeypatch)
    create_user(conn, "a@x.dev", "pw", "developer")
    leaver, _ = create_user(conn, "gone@x.dev", "pw", "developer")
    set_active(conn, leaver.id, False)  # already inactive → excluded

    c = open_campaign(conn, "Q3 review", admin.id, days=30)
    emails = {i.email for i in list_items(conn, c.id)}
    assert emails == {"admin@x.dev", "a@x.dev"}  # inactive user not included
    assert recert_progress(conn, c.id) == {"total": 2, "certified": 0, "revoked": 0, "pending": 2}


def test_revoke_deactivates_user_and_certify_keeps(monkeypatch):
    conn, admin = _conn(monkeypatch)
    keep, _ = create_user(conn, "keep@x.dev", "pw", "developer")
    drop, _ = create_user(conn, "drop@x.dev", "pw", "developer")
    c = open_campaign(conn, "review", admin.id)
    audit = SqliteSink(conn)
    items = {i.email: i for i in list_items(conn, c.id)}

    decide_item(conn, items["keep@x.dev"].id, Verdict("certified", admin.id), audit)
    decide_item(conn, items["drop@x.dev"].id, Verdict("revoked", admin.id), audit)

    assert authenticate(conn, "keep@x.dev", "pw") is not None      # kept
    assert authenticate(conn, "drop@x.dev", "pw") is None          # revoked → deactivated
    assert any(e.recipe == "recert-decision" for e in query_events(conn))


def test_campaign_closes_when_all_decided(monkeypatch):
    conn, admin = _conn(monkeypatch)
    c = open_campaign(conn, "solo", admin.id)  # only admin
    audit = SqliteSink(conn)
    item = list_items(conn, c.id)[0]
    decide_item(conn, item.id, Verdict("certified", admin.id), audit)
    from open_refinery.recert import get_campaign
    assert get_campaign(conn, c.id).status == "closed"


def test_bad_decision_rejected(monkeypatch):
    conn, admin = _conn(monkeypatch)
    c = open_campaign(conn, "x", admin.id)
    item = list_items(conn, c.id)[0]
    with pytest.raises(ValueError):
        decide_item(conn, item.id, Verdict("maybe", admin.id), SqliteSink(conn))


def test_open_campaign_http_response_carries_fields(monkeypatch):
    # regression: the items-commit expired the campaign → the create response was {}
    from fastapi.testclient import TestClient
    conn, admin = _conn(monkeypatch)
    token = __import__("open_refinery").rotate_token(conn, admin.id)
    from open_refinery.web import create_app
    client = TestClient(create_app(conn))
    r = client.post("/recert/campaigns", headers={"Authorization": f"Bearer {token}"},
                    json={"name": "http", "days": 30})
    assert r.status_code == 201 and r.json()["id"] and r.json()["status"] == "open"


def test_overdue_emits_once(monkeypatch):
    conn, admin = _conn(monkeypatch)
    c = open_campaign(conn, "late", admin.id, days=1)
    audit = SqliteSink(conn)
    later = (datetime.fromisoformat(now_iso()) + timedelta(days=2)).isoformat()

    assert [x.id for x in overdue_campaigns(conn, later)] == [c.id]
    assert emit_recert_overdue(conn, audit, later) == [c.id]
    assert any(e.recipe == "recert-overdue" for e in query_events(conn))
    assert emit_recert_overdue(conn, audit, later) == []  # deduped
