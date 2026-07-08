from fastapi import APIRouter

from ..deps import *  # noqa: F401,F403
from ..web import *  # noqa: F401,F403

router = APIRouter()


@router.get("/experiments")
def get_experiments(layer: str | None = None, session: Session = Depends(get_session),
                    _: User = Depends(current_user)):
    return list_experiments(session, layer=layer)

@router.post("/experiments", status_code=201)
def add_experiment(body: NewExperiment, session: Session = Depends(get_session),
                   user: User = Depends(current_user)):
    return create_experiment(session, body.name, body.hypothesis, body.change, body.layer, user.id)

@router.post("/experiments/{experiment_id}/evals", status_code=201)
def add_eval(experiment_id: str, body: NewEval, session: Session = Depends(get_session),
             _: User = Depends(current_user)):
    return record_eval(session, experiment_id, body.phase, body.metric, body.samples,
                       round=body.round)

@router.get("/experiments/{experiment_id}/analysis", dependencies=[Depends(current_user)])
def get_analysis(experiment_id: str, metric: str | None = None, round: int | None = None,
                 session: Session = Depends(get_session)):
    return analyze_experiment(session, experiment_id, metric=metric, round=round)

@router.post("/experiments/{experiment_id}/conclude")
def end_experiment(experiment_id: str, session: Session = Depends(get_session),
                   _: User = Depends(current_user)):
    return conclude_experiment(session, experiment_id)

# --- webhooks (fan audit events out; HMAC-signed) ---
@router.get("/webhooks")
def get_webhooks(session: Session = Depends(get_session),
                 _: User = Depends(require("platform", "admin"))):
    return list_webhooks(session)  # secret is encrypted, never returned

@router.post("/webhooks", status_code=201)
def add_webhook(body: NewWebhook, session: Session = Depends(get_session),
                user: User = Depends(require("platform", "admin"))):
    wh, secret = create_webhook(session, body.url, body.events, user.id)
    return {"webhook": wh, "secret": secret}  # secret shown once

@router.delete("/webhooks/{webhook_id}")
def remove_webhook(webhook_id: str, session: Session = Depends(get_session),
                   _: User = Depends(require("platform", "admin"))):
    delete_webhook(session, webhook_id)
    return {"status": "deleted"}

# --- debt audits & health ---
@router.get("/health/areas")
def get_area_health(session: Session = Depends(get_session), _: User = Depends(current_user)):
    return health(session)  # live factory/harness/charter scores

@router.get("/audits")
def get_audits(area: str | None = None, session: Session = Depends(get_session),
               _: User = Depends(current_user)):
    return list_audits(session, area=area)

@router.post("/audits/run", status_code=201)
def run_audits(area: str = "all", background: bool = False,
               session: Session = Depends(get_session), user: User = Depends(current_user)):
    if background:  # run off the request path; poll /jobs/{id}
        return enqueue(session, session.get_bind(), f"audit:{area}",
                       lambda s: {"audits": [a.id for a in run_audit(s, area, user.id)]})
    return run_audit(session, area, user.id)

# --- background jobs ---
@router.get("/jobs")
def get_jobs(session: Session = Depends(get_session), _: User = Depends(current_user)):
    return list_jobs(session)

@router.get("/jobs/{job_id}")
def get_one_job(job_id: str, session: Session = Depends(get_session), _: User = Depends(current_user)):
    job = get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job")
    return job

# --- systems (compose repos into services) ---
