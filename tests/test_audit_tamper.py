"""Tamper resistance of the audit chain.

The product's central claim is that the log can be trusted. These are the
attacks that claim has to survive, written as the attacker would run them:
with full write access to the database and no access to `SECRET_KEY`.

Two of them passed silently before this suite existed — a forged event with a
recomputed chain, and deletion of the oldest events — so each one here is a
regression test for a real hole, not a hypothetical.
"""

import pytest
from sqlmodel import select

from open_refinery.models import AuditChainState, Event
from open_refinery.provenance import Record
from open_refinery.store import (
    SqlSink,
    _entry_hash,
    connect,
    export_chain,
    purge_events,
    verify_chain,
)


def _store(n=5):
    session = connect("sqlite:///:memory:")
    sink = SqlSink(session)
    for i in range(n):
        sink.write(Record.of(recipe="invoke", actor="alice", owner="alice",
                             inputs={"n": i}, output=f"out-{i}"))
    return session


def _ordered(session):
    return sorted(session.exec(select(Event)).all(), key=lambda e: e.created_at)


def _force_delete(session, events):
    """Delete rows the way an attacker with SQL access would — around the ORM
    and around any append-only trigger."""
    ids = [e.artifact_id for e in events]
    for artifact_id in ids:
        session.exec(  # noqa: S608 — parameterized below
            __import__("sqlalchemy").text(
                "DELETE FROM events WHERE artifact_id = :i").bindparams(i=artifact_id))
    session.commit()
    session.expire_all()


# --- the baseline -----------------------------------------------------------

def test_an_untouched_chain_verifies():
    assert verify_chain(_store())["ok"] is True


def test_an_empty_chain_verifies():
    assert verify_chain(connect("sqlite:///:memory:"))["ok"] is True


# --- attack 1: forge an event and recompute the chain -----------------------

def _recompute_unkeyed(session, events):
    """Rebuild the whole chain the way an attacker without SECRET_KEY must:
    with the plain sha256 construction, which is all they can compute."""
    import hashlib

    from open_refinery.store import _canonical

    prev = events[0].prev_hash
    for e in events:
        e.prev_hash = prev
        e.entry_hash = hashlib.sha256((prev + _canonical(e)).encode()).hexdigest()
        prev = e.entry_hash
        session.add(e)
    state = session.get(AuditChainState, "head")
    state.head = prev
    session.add(state)
    session.commit()


def test_forging_an_event_and_recomputing_the_chain_is_detected():
    """THE important one. An unkeyed hash lets anyone with database write access
    rewrite who did what, recompute every link, and pass verification. The chain
    must be keyed so recomputation needs a secret the database does not hold."""
    session = _store()
    events = _ordered(session)
    events[2].actor = "mallory-was-never-here"
    _recompute_unkeyed(session, events)

    assert verify_chain(session)["ok"] is False


def test_downgrading_the_algorithm_to_forge_the_chain_is_detected():
    """The attacker's next move once the chain is keyed: relabel the rows as
    the old unkeyed construction, which they *can* compute, and recompute.
    Once a chain is keyed it must never accept a legacy row after that point."""
    session = _store()
    events = _ordered(session)
    events[2].actor = "mallory-was-never-here"
    for e in events:
        e.chain_algo = "sha256"          # claim these predate the keyed chain
    _recompute_unkeyed(session, events)

    assert verify_chain(session)["ok"] is False


def test_a_genuinely_legacy_chain_still_verifies():
    """An install upgrading from before 2.13 holds unkeyed rows. They must keep
    verifying, or the upgrade reads as tampering."""
    import hashlib

    from open_refinery.models import Event
    from open_refinery.store import _canonical

    session = connect("sqlite:///:memory:")
    prev = ""
    for i in range(3):
        e = Event(artifact_id=f"legacy-{i}", recipe="invoke", actor="alice",
                  owner="alice", input_digest="d", output_digest=f"o{i}",
                  created_at=f"2024-01-0{i + 1}T00:00:00+00:00",
                  prev_hash=prev, chain_algo="sha256")
        e.entry_hash = hashlib.sha256((prev + _canonical(e)).encode()).hexdigest()
        prev = e.entry_hash
        session.add(e)
    session.add(AuditChainState(id="head", head=prev))
    session.commit()

    assert verify_chain(session)["ok"] is True


def test_editing_one_field_without_recomputing_is_detected():
    session = _store()
    events = _ordered(session)
    events[2].output_digest = "0" * 64
    session.add(events[2])
    session.commit()

    assert verify_chain(session)["ok"] is False


# --- attack 2: delete the oldest events -------------------------------------

def test_deleting_the_oldest_events_is_detected():
    """Was read as a legitimate purge and reported `ok`. A gap must be explained
    by a signed checkpoint or it is tampering."""
    session = _store(6)
    _force_delete(session, _ordered(session)[:2])

    result = verify_chain(session)
    assert result["ok"] is False
    assert "gap" in result.get("broken_at", "").lower()


def test_deleting_every_event_is_detected():
    session = _store(4)
    _force_delete(session, _ordered(session))

    assert verify_chain(session)["ok"] is False


# --- attacks 3 & 4: already caught, kept so they stay caught ----------------

def test_deleting_a_mid_chain_event_is_detected():
    session = _store()
    _force_delete(session, [_ordered(session)[2]])
    assert verify_chain(session)["ok"] is False


def test_truncating_the_tail_is_detected():
    session = _store()
    _force_delete(session, [_ordered(session)[-1]])
    assert verify_chain(session)["ok"] is False


# --- legitimate retention stays legitimate ----------------------------------

def test_a_recorded_purge_leaves_a_chain_that_still_verifies():
    """Retention is a real requirement. It must not be indistinguishable from
    an attack, and it must not break the log either."""
    session = _store(5)
    purge_events(session, older_than_days=0)   # everything is older than 0 days

    assert verify_chain(session)["ok"] is True


def test_a_purge_records_a_signed_checkpoint_naming_what_went():
    from open_refinery.models import AuditCheckpoint

    session = _store(5)
    removed = purge_events(session, older_than_days=0)

    checkpoints = list(session.exec(select(AuditCheckpoint)))
    assert len(checkpoints) == 1
    assert checkpoints[0].deleted_count == removed
    assert checkpoints[0].signature


def test_forging_a_checkpoint_to_excuse_a_deletion_is_detected():
    """The obvious next move once gaps need explaining: delete events, then
    write a checkpoint claiming it was a purge. The signature must stop it."""
    from open_refinery.models import AuditCheckpoint

    session = _store(6)
    events = _ordered(session)
    _force_delete(session, events[:2])
    session.add(AuditCheckpoint(kind="purge", deleted_count=2,
                                cut_to=events[2].prev_hash, head="",
                                signature="not-a-real-signature"))
    session.commit()

    assert verify_chain(session)["ok"] is False


# --- the export an auditor is handed ----------------------------------------

def test_export_signature_covers_the_events_not_just_the_head():
    """Signing only the head lets an attacker who rewrote history export a
    perfectly valid signature over their forged head."""
    session = _store(3)
    good = export_chain(session)

    tampered = dict(good)
    tampered["events"] = good["events"][1:]          # drop one from the export
    from open_refinery.store import verify_export
    assert verify_export(good)["ok"] is True
    assert verify_export(tampered)["ok"] is False


@pytest.mark.parametrize("field", ["actor", "recipe", "output_digest"])
def test_export_detects_a_field_edited_after_export(field):
    session = _store(3)
    export = export_chain(session)
    export["events"][1][field] = "changed-after-the-fact"

    from open_refinery.store import verify_export
    assert verify_export(export)["ok"] is False
