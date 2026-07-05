import time

from open_refinery import connect, create_job, enqueue, get_job, list_jobs, run_job
from open_refinery.store import engine_for


def test_run_job_records_result():
    url = "sqlite:///:memory:"
    engine = engine_for(url)
    conn = __import__("sqlmodel").Session(engine)
    job = create_job(conn, "demo")
    assert job.status == "pending"
    run_job(engine, job.id, lambda s: {"answer": 42})
    conn.expire_all()
    done = get_job(conn, job.id)
    assert done.status == "done" and done.result == {"answer": 42}


def test_run_job_records_failure():
    engine = engine_for("sqlite:///:memory:")
    conn = __import__("sqlmodel").Session(engine)
    job = create_job(conn, "boom")

    def fn(_s):
        raise RuntimeError("kaboom")

    run_job(engine, job.id, fn)
    conn.expire_all()
    failed = get_job(conn, job.id)
    assert failed.status == "failed" and "kaboom" in failed.error


def test_enqueue_runs_in_background(tmp_path):
    url = f"sqlite:///{tmp_path/'jobs.db'}"
    engine = engine_for(url)
    from sqlmodel import Session
    conn = Session(engine)
    job = enqueue(conn, engine, "bg", lambda s: {"ok": True})
    assert job.status == "pending"  # returns immediately

    for _ in range(50):             # poll until the daemon thread finishes
        conn.expire_all()
        j = get_job(conn, job.id)
        if j.status in ("done", "failed"):
            break
        time.sleep(0.02)
    assert j.status == "done" and j.result == {"ok": True}
    assert len(list_jobs(conn)) == 1
