"""Permissions and presets — the surface behind "add the users, give them
permissions".

Reading is open to any authenticated user: "who can approve a harness change"
is a question everyone needs answered, and hiding it only means asking around.
Changing anything here is `manage:users`.
"""

from fastapi import APIRouter

from .. import authority
from ..deps import *  # noqa: F401,F403
from ..models import Role
from ..web import *  # noqa: F401,F403
from ..users import set_permissions

router = APIRouter()


@router.get("/permissions")
def get_permissions(_: User = Depends(current_user)):
    """The whole vocabulary, each with a line saying what it means — a checkbox
    you have to guess at is one that gets ticked."""
    return {"permissions": authority.catalog(), "layers": list(authority.LAYERS)}


@router.get("/permissions/approvers/{layer}")
def get_approvers(layer: str, session: Session = Depends(get_session),
                  _: User = Depends(current_user)):
    """Who can sign off this layer. What somebody blocked needs is a person."""
    return {"layer": layer, "approvers": authority.approvers_of(session, layer)}


# --- presets: the defaults to build from ------------------------------------

@router.put("/presets/{name}")
def upsert_preset(name: str, body: PresetBody, session: Session = Depends(get_session),
                  user: User = Depends(manages_users)):
    """Create or update a preset.

    A preset is a **starting point**, not a role: it is copied onto a user at
    creation and never read again, so editing one changes nobody who already
    exists. The UI says so rather than letting people assume otherwise.
    """
    row = session.get(Role, name)
    if row is not None and row.builtin:
        raise HTTPException(status_code=403,
                            detail=f"{name!r} is a shipped preset and cannot be changed")
    unknown = [p for p in body.permissions if not authority.valid(p)]
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown permissions: {unknown}")

    preset = create_role(session, name, body.rank, permissions=body.permissions)
    SqliteSink(session).write(Record.of(
        recipe="preset-changed", actor=user.id, owner=user.id,
        inputs={"permissions": preset.permissions}, output=name, subject=name))
    return {"name": preset.name, "rank": preset.rank,
            "permissions": preset.permissions, "builtin": preset.builtin}


@router.delete("/presets/{name}")
def remove_preset(name: str, session: Session = Depends(get_session),
                  user: User = Depends(manages_users)):
    try:
        delete_role(session, name)
    except RoleInUse as exc:
        raise HTTPException(status_code=409,
                            detail=f"{name!r} is still assigned to a user") from exc
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    SqliteSink(session).write(Record.of(
        recipe="preset-removed", actor=user.id, owner=user.id,
        inputs={}, output=name, subject=name))
    return {"status": "deleted"}


# --- a person's permissions -------------------------------------------------

@router.get("/users/{user_id}/permissions")
def get_user_permissions(user_id: str, session: Session = Depends(get_session),
                         user: User = Depends(current_user)):
    """Your own, or anyone's if you manage users. Everyone can see what they
    hold — being unable to answer "what am I allowed to do" is its own problem."""
    if user_id != user.id and not authority.manages_users(user):
        raise HTTPException(status_code=403, detail="you do not hold manage:users")
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="unknown user")
    return authority.describe(target)


@router.put("/users/{user_id}/permissions")
def put_user_permissions(user_id: str, body: PermissionsBody,
                         session: Session = Depends(get_session),
                         user: User = Depends(manages_users)):
    """Set what a person may do.

    Refuses your own account: granting yourself a permission you do not hold is
    the one thing any permission model has to make impossible, and holding
    `manage:users` must not quietly imply holding everything else.
    """
    if user_id == user.id:
        raise HTTPException(
            status_code=403,
            detail="you cannot change your own permissions — ask someone else")

    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="unknown user")

    wanted = list(body.permissions)
    if body.preset:
        wanted = authority.of_preset(body.preset) + wanted
    unknown = [p for p in wanted if not authority.valid(p)]
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown permissions: {unknown}")

    before = list(target.permissions or [])
    updated = set_permissions(session, user_id, wanted)
    SqliteSink(session).write(Record.of(
        recipe="permissions-changed", actor=user.id, owner=user.id,
        inputs={"before": before, "after": updated.permissions},
        output=target.email, subject=user_id))
    return authority.describe(updated)
