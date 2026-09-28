from fastapi import APIRouter

from ..deps import *  # noqa: F401,F403
from ..web import *  # noqa: F401,F403

router = APIRouter()


# --- routes ---
@router.get("/health")
def healthcheck():  # not `health` — that name is the imported debt.health scorer
    return {"status": "ok"}

# --- first-run onboarding: the first admin runs the setup wizard; once
# complete, later users inherit the configured org and skip it. ---
@router.get("/onboarding")
def onboarding_status(session: Session = Depends(get_session), _: User = Depends(current_user)):
    return {"onboarded": (get_setting(session, "org.onboarded") or "").lower() == "true"}

@router.post("/onboarding/complete")
def onboarding_complete(session: Session = Depends(get_session),
                        user: User = Depends(sees_operations)):
    set_setting(session, "org.onboarded", "true", user.id)
    return {"onboarded": True}

@router.get("/api-docs", include_in_schema=False)
def api_docs():
    # self-hosted Swagger UI; assets copied into static/api-docs-assets at build
    return get_swagger_ui_html(
        openapi_url="/openapi.json", title="open-refinery API",
        swagger_js_url="/api-docs-assets/swagger-ui-bundle.js",
        swagger_css_url="/api-docs-assets/swagger-ui.css")

@router.get("/setup/status")
def setup_status(session: Session = Depends(get_session)):
    return {"needs_setup": count_users(session) == 0}

@router.post("/setup", status_code=201)
def setup(body: Setup, session: Session = Depends(get_session)):
    """The first account, and the defaults it builds from.

    **The first account holds everything**, because it is the owner of the
    installation rather than an admin somebody appointed. The `admin` preset is
    deliberately narrow — add people, read the trail — and on a fresh install
    that is a dead end: there is nobody else, and nobody may change their own
    permissions (separation of duties, correctly). The owner would have had to
    invent a second person to be granted anything by. So the first account gets
    the full set and delegates from there, which is the direction authority is
    supposed to flow.

    A fresh install also seeds `ship-a-ticket` here, because a workflow needs an
    owner and this is the first moment there is one. Without it, an install has
    no pipeline at all and the first `POST /runs` fails on a name nobody typed —
    "defaults to build from" is only true if they are actually there.
    """
    from ..authority import PERMISSIONS
    from ..pipeline import store as ps

    if count_users(session) > 0:
        raise HTTPException(status_code=409, detail="already set up")
    user, token = create_user(session, body.email, body.password, "admin",
                              permissions=list(PERMISSIONS))
    ps.ensure_default(session, user.id)
    session.refresh(user)   # seeding committed, which expired the row we return
    return {"user": user, "token": token}

@router.get("/me")
def me(user: User = Depends(current_user)):
    return public_user(user)  # never expose pw_hash / pw_salt / token_hash

@router.post("/me/token/rotate")
def rotate_my_token(session: Session = Depends(get_session), user: User = Depends(current_user)):
    return {"token": rotate_token(session, user.id)}  # old API token invalidated

# --- roles ---
@router.get("/roles")
def get_roles(session: Session = Depends(get_session), _: User = Depends(current_user)):
    """Every role and the powers it carries. Open to any authenticated user:
    "who approves a harness change" is a question everyone needs answered.

    Defining them lives in `routers/roles.py`. The note that used to sit here —
    that arbitrary roles "proved confusing" — was right about the symptom and
    wrong about the cause: a role that was only a *rank* meant nothing. Powers
    on the row make a custom role legible, so they are exposed again.
    """
    return list_roles(session)


# --- evals & experiments (test if a change's effect is real) ---
