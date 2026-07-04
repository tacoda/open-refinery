import pytest

from open_refinery import (
    analyze_experiment,
    conclude_experiment,
    connect,
    create_experiment,
    create_user,
    list_experiments,
    record_eval,
)


def setup():
    conn = connect("sqlite:///:memory:")
    dev, _ = create_user(conn, "dev@x.dev", "pw", "developer")
    exp = create_experiment(conn, "faster reviews", "the new prompt cuts review time",
                            "swap review prompt", "harness", dev.id)
    return conn, dev, exp


def test_create_and_list():
    conn, dev, exp = setup()
    assert exp.status == "running" and exp.layer == "harness"
    assert len(list_experiments(conn, layer="harness")) == 1
    assert list_experiments(conn, layer="project") == []


def test_record_eval_summarizes():
    conn, dev, exp = setup()
    run = record_eval(conn, exp.id, "before", "minutes", [10, 12, 11, 13, 9])
    assert run.n == 5 and 10 < run.mean < 12 and run.std > 0


def test_analysis_detects_significant_improvement():
    conn, dev, exp = setup()
    # metric where lower is worse; after is clearly higher (improvement in "score")
    record_eval(conn, exp.id, "before", "score", [50, 52, 48, 51, 49, 50])
    record_eval(conn, exp.id, "after", "score", [70, 72, 68, 71, 69, 70])
    res = analyze_experiment(conn, exp.id, metric="score")
    assert res["significant"] is True and res["verdict"] == "significant improvement"
    assert res["delta"] > 0 and res["p_value"] < 0.05 and res["cohen_d"] > 0


def test_analysis_no_effect_when_overlapping():
    conn, dev, exp = setup()
    record_eval(conn, exp.id, "before", "score", [50, 55, 45, 52, 48])
    record_eval(conn, exp.id, "after", "score", [51, 54, 46, 53, 47])
    res = analyze_experiment(conn, exp.id, metric="score")
    assert res["significant"] is False and res["verdict"] == "no significant effect"


def test_analysis_insufficient_data():
    conn, dev, exp = setup()
    record_eval(conn, exp.id, "before", "score", [1, 2, 3])
    res = analyze_experiment(conn, exp.id, metric="score")
    assert res["verdict"] == "insufficient data" and res["significant"] is False


def test_iterate_rounds_uses_latest():
    conn, dev, exp = setup()
    record_eval(conn, exp.id, "before", "score", [50, 51, 49], round=1)
    record_eval(conn, exp.id, "after", "score", [50, 51, 49], round=1)   # no effect round 1
    record_eval(conn, exp.id, "before", "score", [50, 51, 49], round=2)
    record_eval(conn, exp.id, "after", "score", [80, 81, 79], round=2)   # big effect round 2
    res = analyze_experiment(conn, exp.id, metric="score")               # latest round wins
    assert res["significant"] is True


def test_conclude():
    conn, dev, exp = setup()
    assert conclude_experiment(conn, exp.id).status == "concluded"


def test_bad_layer_and_phase():
    conn, dev, exp = setup()
    with pytest.raises(ValueError):
        create_experiment(conn, "x", "h", "c", "nope", dev.id)
    with pytest.raises(ValueError):
        record_eval(conn, exp.id, "sideways", "m", [1, 2])
