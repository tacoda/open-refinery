from fastapi import APIRouter, Request, Response

from .. import scim
from ..deps import *  # noqa: F401,F403
from ..users import set_active, valid_role
from ..web import *  # noqa: F401,F403

router = APIRouter()


# --- SCIM protocol (IdP → platform), authenticated with the provisioning token ---
def scim_auth(request: Request, session: Session = Depends(get_session)):
    token = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    if not scim.verify_token(session, token):
        raise HTTPException(status_code=401, detail="invalid scim token")


def _group_names(payload: dict) -> list[str]:
    out = []
    for g in payload.get("groups") or []:
        out.append((g.get("display") or g.get("value")) if isinstance(g, dict) else g)
    return [g for g in out if g]


def _email(payload: dict) -> str:
    return payload.get("userName") or (payload.get("emails") or [{}])[0].get("value", "")


@router.post("/scim/v2/Users", status_code=201, dependencies=[Depends(scim_auth)])
def scim_create(payload: dict, session: Session = Depends(get_session)):
    email = _email(payload)
    if not email:
        raise HTTPException(status_code=400, detail="userName required")
    role = scim.role_from_groups(session, _group_names(payload))
    user, _ = create_user(session, email, secrets.token_urlsafe(16), role)  # SSO login; pw unused
    if payload.get("active") is False:
        user = set_active(session, user.id, False)
    return scim.to_scim(user)


@router.get("/scim/v2/Users", dependencies=[Depends(scim_auth)])
def scim_list(session: Session = Depends(get_session), filter: str | None = None):
    users = list_users(session)
    if filter and " eq " in filter:               # e.g. userName eq "a@x.dev"
        wanted = filter.split(" eq ", 1)[1].strip().strip('"')
        users = [u for u in users if u.email == wanted]
    return scim.list_response(users)


@router.get("/scim/v2/Users/{user_id}", dependencies=[Depends(scim_auth)])
def scim_get(user_id: str, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return scim.to_scim(user)


def _apply_active(payload: dict) -> bool | None:
    """Extract an active flag from a SCIM PATCH/PUT body (Okta/Entra shapes)."""
    if "active" in payload:
        return payload["active"]
    for op in payload.get("Operations", []):
        val = op.get("value")
        if op.get("path") == "active":
            return val
        if isinstance(val, dict) and "active" in val:
            return val["active"]
    return None


@router.put("/scim/v2/Users/{user_id}", dependencies=[Depends(scim_auth)])
@router.patch("/scim/v2/Users/{user_id}", dependencies=[Depends(scim_auth)])
def scim_update(user_id: str, payload: dict, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    active = _apply_active(payload)
    if active is not None:
        user = set_active(session, user_id, active)
    return scim.to_scim(user)


@router.delete("/scim/v2/Users/{user_id}", dependencies=[Depends(scim_auth)])
def scim_delete(user_id: str, session: Session = Depends(get_session)):
    set_active(session, user_id, False)  # soft-deactivate; keep audit history
    return Response(status_code=204)


# --- admin configuration (user token, admin only) ---
@router.get("/scim/config")
def scim_config(session: Session = Depends(get_session), _: User = Depends(require("admin"))):
    return {"enabled": scim.configured(session), "group_map": scim.group_map(session),
            "default_role": scim.default_role(session)}

@router.post("/scim/token")
def scim_rotate_token(session: Session = Depends(get_session),
                      user: User = Depends(require("admin"))):
    return {"token": scim.rotate_token(session, user.id)}  # shown once

@router.post("/scim/group-map")
def scim_set_group_map(body: ScimGroupMap, session: Session = Depends(get_session),
                       user: User = Depends(require("admin"))):
    if not valid_role(session, body.default_role):
        raise HTTPException(status_code=400, detail="invalid default role")
    for role in body.map.values():
        if not valid_role(session, role):
            raise HTTPException(status_code=400, detail=f"invalid role: {role}")
    scim.set_group_map(session, body.map, body.default_role, user.id)
    return {"ok": True}
