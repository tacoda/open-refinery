import pytest

from open_refinery import AllowList, Factory, MemorySink, Unauthorized
from open_refinery.factory import UnknownRecipe


def make_factory(**kw):
    f = Factory(**kw)
    f.register("upper", lambda text: text.upper())
    return f


def test_produce_returns_artifact_and_record():
    f = make_factory()
    artifact, record = f.produce("upper", actor="ian", text="hi")
    assert artifact == "HI"
    assert record.recipe == "upper"
    assert record.actor == "ian"
    assert record.owner == "ian"  # defaults to actor
    assert record.artifact_id
    assert record.input_digest and record.output_digest


def test_owner_override():
    f = make_factory()
    _, record = f.produce("upper", actor="ian", owner="team", text="hi")
    assert record.owner == "team"


def test_audit_trail_records_every_production():
    sink = MemorySink()
    f = make_factory(audit=sink)
    f.produce("upper", actor="ian", text="a")
    f.produce("upper", actor="ian", text="b")
    assert len(sink.records) == 2
    assert {r.output_digest for r in sink.records}  # distinct digests captured


def test_unknown_recipe():
    f = make_factory()
    with pytest.raises(UnknownRecipe):
        f.produce("missing", actor="ian")


def test_authorization_blocks_disallowed_actor():
    f = make_factory(authorizer=AllowList({("ian", "upper")}))
    f.produce("upper", actor="ian", text="ok")  # allowed
    with pytest.raises(Unauthorized):
        f.produce("upper", actor="mallory", text="no")


def test_unauthorized_leaves_no_audit_record():
    sink = MemorySink()
    f = make_factory(authorizer=AllowList(set()), audit=sink)
    with pytest.raises(Unauthorized):
        f.produce("upper", actor="ian", text="no")
    assert sink.records == []
