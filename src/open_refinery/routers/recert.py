from fastapi import APIRouter

from .. import recert
from ..deps import *  # noqa: F401,F403
from ..web import *  # noqa: F401,F403

router = APIRouter()

_review = require("platform", "admin")  # who runs recertification


@router.post("/recert/campaigns", status_code=201)
def open_campaign(body: NewCampaign, session: Session = Depends(get_session),
                  user: User = Depends(_review)):
    return recert.open_campaign(session, body.name, user.id, body.days)


@router.get("/recert/campaigns")
def list_campaigns(session: Session = Depends(get_session), _: User = Depends(oversight)):
    return [{**c.model_dump(), "progress": recert.progress(session, c.id)}
            for c in recert.list_campaigns(session)]


@router.get("/recert/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, session: Session = Depends(get_session),
                 _: User = Depends(oversight)):
    campaign = recert.get_campaign(session, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return {"campaign": campaign, "items": recert.list_items(session, campaign_id),
            "progress": recert.progress(session, campaign_id)}


@router.post("/recert/items/{item_id}/decide")
def decide(item_id: str, body: RecertDecision, session: Session = Depends(get_session),
           user: User = Depends(_review)):
    verdict = recert.Verdict(body.decision, user.id, body.note)
    return recert.decide_item(session, item_id, verdict, SqliteSink(session))
