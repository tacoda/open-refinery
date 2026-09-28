"""The ladder over HTTP — and the asymmetry that stops being a comment here.

A promotion adds enforcement and needs the layer's owner. A demotion **removes**
it, and needs the owner *and* a second signer, because one person removing
enforcement on their own is the thing an auditor asks about.
"""

import pytest
from fastapi.testclient import TestClient

from open_refinery.store import connect
from open_refinery.users import create_session, create_user, ensure_presets
from open_refinery.web import create_app


@pytest.fixture
def ctx():
    session = connect("sqlite:///:memory:", check_same_thread=False)
    ensure_presets(session)
    people = {p: create_user(session, f"{p}@x.io", "pw", p)[0]
              for p in ("developer", "lead", "platform", "admin")}
    people["lead2"] = create_user(session, "lead2@x.io", "pw", "lead")[0]
    client = TestClient(create_app(session))

    def hdr(who):
        return {"Authorization": f"Bearer {create_session(session, people[who].id)}"}

    return session, client, hdr, people


def _rule(client, hdr, who="lead", **kw):
    body = {"text": "No secrets", "layer": "harness", "rung": 0, **kw}
    return client.post("/ladder", headers=hdr(who), json=body)


# --- reading ----------------------------------------------------------------

def test_anyone_can_read_the_ladder(ctx):
    """A constraint nobody can read is one nobody can rely on."""
    _, client, hdr, _ = ctx
    body = client.get("/ladder", headers=hdr("developer")).json()

    assert len(body["rungs"]) == 6
    assert all(r["sees"] for r in body["rungs"])
    assert body["predicates"]


def test_the_rungs_say_which_ones_this_product_carries(ctx):
    """Rung 2 is the repository's own hook and rung 5 is its CI — real, and
    not ours."""
    _, client, hdr, _ = ctx
    rungs = {r["rung"]: r["ours"] for r in client.get("/ladder", headers=hdr("developer")).json()["rungs"]}
    assert rungs[3] is True and rungs[2] is False and rungs[5] is False


# --- authoring --------------------------------------------------------------

def test_the_layers_owner_can_add_a_rule(ctx):
    _, client, hdr, _ = ctx
    assert _rule(client, hdr, "lead", layer="harness").status_code == 201


def test_somebody_else_cannot_and_is_told_who_can(ctx):
    _, client, hdr, _ = ctx
    r = _rule(client, hdr, "developer", layer="harness")
    assert r.status_code == 403 and "lead@x.io" in r.json()["detail"]


def test_a_factory_rule_is_platforms(ctx):
    _, client, hdr, _ = ctx
    assert _rule(client, hdr, "platform", layer="factory").status_code == 201
    assert _rule(client, hdr, "lead", layer="factory").status_code == 403


def test_a_mechanical_rung_without_a_predicate_is_a_400(ctx):
    _, client, hdr, _ = ctx
    r = _rule(client, hdr, "lead", rung=3)
    assert r.status_code == 400 and "predicate" in r.json()["detail"]


def test_adding_a_rule_is_audited(ctx):
    _, client, hdr, _ = ctx
    _rule(client, hdr, "lead")
    events = client.get("/events", headers=hdr("admin")).json()
    assert any(e["recipe"] == "ladder-added" for e in events)


# --- previewing a move ------------------------------------------------------

def test_a_preview_says_what_it_would_take(ctx):
    """Pure, so "what would it take to make this real?" can be asked freely."""
    _, client, hdr, _ = ctx
    rule = _rule(client, hdr, "lead").json()

    body = client.get(f"/ladder/{rule['id']}/move?to=3", headers=hdr("developer")).json()
    assert body["direction"] == "promotion"
    assert body["needs_predicate"] is True
    assert body["needs_second_signer"] is False
    assert "callback in the turn" in body["sees"]


def test_a_preview_of_a_demotion_says_it_needs_two(ctx):
    _, client, hdr, _ = ctx
    rule = _rule(client, hdr, "lead", rung=3, predicate="no-secrets").json()

    body = client.get(f"/ladder/{rule['id']}/move?to=0", headers=hdr("developer")).json()
    assert body["direction"] == "demotion" and body["needs_second_signer"] is True


# --- promotion --------------------------------------------------------------

def test_a_promotion_needs_one_approver(ctx):
    _, client, hdr, _ = ctx
    rule = _rule(client, hdr, "lead").json()

    r = client.post(f"/ladder/{rule['id']}/move", headers=hdr("lead"),
                    json={"to": 3, "predicate": "no-secrets"})
    assert r.status_code == 200 and r.json()["rung"] == 3


def test_a_promotion_to_a_rung_nothing_enforces_is_refused(ctx):
    """Worse than leaving it at rung 0, because it looks enforced."""
    _, client, hdr, _ = ctx
    rule = _rule(client, hdr, "lead").json()

    r = client.post(f"/ladder/{rule['id']}/move", headers=hdr("lead"), json={"to": 3})
    assert r.status_code == 400 and "looks enforced" in r.json()["detail"]


def test_a_promotion_is_audited_as_one(ctx):
    _, client, hdr, _ = ctx
    rule = _rule(client, hdr, "lead").json()
    client.post(f"/ladder/{rule['id']}/move", headers=hdr("lead"),
                json={"to": 3, "predicate": "no-secrets"})

    recipes = [e["recipe"] for e in client.get("/events", headers=hdr("admin")).json()]
    assert "ladder-promotion" in recipes


# --- demotion: the one move that makes the system weaker --------------------

def test_a_demotion_without_a_second_signer_is_refused(ctx):
    _, client, hdr, _ = ctx
    rule = _rule(client, hdr, "lead", rung=3, predicate="no-secrets").json()

    r = client.post(f"/ladder/{rule['id']}/move", headers=hdr("lead"), json={"to": 0})
    assert r.status_code == 400 and "second signer" in r.json()["detail"]


def test_the_second_signer_must_be_somebody_else(ctx):
    """Signing your own demotion is not two people."""
    _, client, hdr, _ = ctx
    rule = _rule(client, hdr, "lead", rung=3, predicate="no-secrets").json()

    r = client.post(f"/ladder/{rule['id']}/move", headers=hdr("lead"),
                    json={"to": 0, "second_signer": "lead@x.io"})
    assert r.status_code == 400 and "somebody else" in r.json()["detail"]


def test_the_second_signer_must_hold_the_authority(ctx):
    """A signature from somebody who could not have approved it is not a
    signature."""
    _, client, hdr, _ = ctx
    rule = _rule(client, hdr, "lead", rung=3, predicate="no-secrets").json()

    r = client.post(f"/ladder/{rule['id']}/move", headers=hdr("lead"),
                    json={"to": 0, "second_signer": "developer@x.io"})
    assert r.status_code == 400 and "approve:harness" in r.json()["detail"]


def test_a_demotion_with_two_real_signers_lands(ctx):
    _, client, hdr, _ = ctx
    rule = _rule(client, hdr, "lead", rung=3, predicate="no-secrets").json()

    r = client.post(f"/ladder/{rule['id']}/move", headers=hdr("lead"),
                    json={"to": 0, "second_signer": "lead2@x.io"})
    assert r.status_code == 200 and r.json()["rung"] == 0


def test_a_demotion_is_audited_with_both_names(ctx):
    """The record an auditor actually asks for."""
    _, client, hdr, _ = ctx
    rule = _rule(client, hdr, "lead", rung=3, predicate="no-secrets").json()
    client.post(f"/ladder/{rule['id']}/move", headers=hdr("lead"),
                json={"to": 0, "second_signer": "lead2@x.io"})

    events = client.get("/events", headers=hdr("admin")).json()
    assert any(e["recipe"] == "ladder-demotion" for e in events)


# --- disabling is a demotion in everything but name -------------------------

def test_an_enforced_rule_cannot_simply_be_switched_off(ctx):
    """Otherwise the two-signer rule is one DELETE away from meaningless."""
    _, client, hdr, _ = ctx
    rule = _rule(client, hdr, "lead", rung=3, predicate="no-secrets").json()

    r = client.delete(f"/ladder/{rule['id']}", headers=hdr("lead"))
    assert r.status_code == 400 and "demote it to rung 0 first" in r.json()["detail"]


def test_prose_can_be_switched_off(ctx):
    _, client, hdr, _ = ctx
    rule = _rule(client, hdr, "lead").json()
    assert client.delete(f"/ladder/{rule['id']}", headers=hdr("lead")).status_code == 200
