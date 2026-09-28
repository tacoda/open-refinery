"""Intake routes — the front door.

`POST /intake/{integration_id}` is the one route in the app with **no bearer
token**: the caller is a tracker, not a person. It authenticates by HMAC over
the exact bytes delivered, which is why the handler takes the raw body and
parses it afterwards — re-serializing a parsed body changes the bytes and the
signature no longer matches anything.
"""

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel

from ..deps import *  # noqa: F401,F403
from ..intake import BadSignature, IntakeError, accept, configure
from ..models import Integration
from ..web import *  # noqa: F401,F403

router = APIRouter()


class IntakeConfig(BaseModel):
    repo_id: str = ""
    pipeline: str = ""
    autostart: bool | None = None
    rotate_secret: bool = False


@router.post("/intake/{integration_id}")
async def receive(integration_id: str, request: Request,
                  x_hub_signature_256: str = Header(default=""),
                  x_gitlab_token: str = Header(default=""),
                  x_signature: str = Header(default="")):
    """Accept a tracker's webhook delivery.

    Unauthenticated by bearer *on purpose* — the signature is the credential.
    A bad signature is a 401 and nothing else: the reply says no more than that,
    because a caller who can distinguish "wrong secret" from "unknown
    integration" can enumerate integrations.
    """
    body = await request.body()
    signature = x_hub_signature_256 or x_gitlab_token or x_signature
    with Session(request.app.state.engine) as session:
        try:
            return accept(session, integration_id, body, signature,
                          audit=SqliteSink(session))
        except BadSignature:
            raise HTTPException(status_code=401, detail="bad signature") from None
        except IntakeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None


@router.put("/integrations/{integ_id}/intake")
def set_intake(integ_id: str, body: IntakeConfig, request: Request,
               session: Session = Depends(get_session), _: User = Depends(may_run)):
    integ, secret = configure(session, integ_id, repo_id=body.repo_id,
                              pipeline=body.pipeline,
                              autostart=body.autostart,
                              rotate_secret=body.rotate_secret)
    return {
        "integration": integ.id,
        "url": f"{base_url(request)}/intake/{integ.id}",
        "repo_id": integ.intake_repo_id,
        "pipeline": integ.intake_pipeline, "autostart": integ.autostart,
        "has_secret": bool(integ.webhook_secret),
        "secret": secret,  # shown once, on rotation only
    }


@router.get("/integrations/{integ_id}/intake")
def get_intake(integ_id: str, request: Request, session: Session = Depends(get_session),
               _: User = Depends(current_user)):
    integ = session.get(Integration, integ_id)
    if integ is None:
        raise HTTPException(status_code=404, detail="unknown integration")
    return {
        "integration": integ.id,
        "url": f"{base_url(request)}/intake/{integ.id}",
        "repo_id": integ.intake_repo_id,
        "pipeline": integ.intake_pipeline, "autostart": integ.autostart,
        "has_secret": bool(integ.webhook_secret),
    }
