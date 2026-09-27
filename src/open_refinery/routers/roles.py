"""Roles — defining them, and what each one may do.

Reading is open to any authenticated user: "who approves a harness change" is a
question everyone needs answered, and hiding the answer only means asking a
person instead. Changing a role is user management, so it is admin's.

The built-in four (plus `auditor`) are a **standard configuration**, not a
limit — a team that wants `reviewer` or two leads split by area writes it down.
"""

from fastapi import APIRouter

from .. import authority
from ..deps import *  # noqa: F401,F403
from ..models import Role
from ..web import *  # noqa: F401,F403

router = APIRouter()


@router.get("/roles/layers")
def get_layers(_: User = Depends(current_user)):
    """What a role's authority can be *about*, for the role editor."""
    return {"layers": list(authority.LAYERS)}


@router.put("/roles/{name}")
def upsert_role(name: str, body: RoleBody, session: Session = Depends(get_session),
                user: User = Depends(manages_users)):
    """Create or update a role and its powers.

    Refuses to edit the caller's **own** role: otherwise the one thing every
    authority model must prevent — granting yourself more authority — is a
    single PUT away.
    """
    if name == user.role:
        raise HTTPException(
            status_code=403,
            detail="you cannot edit the role you hold — ask someone else to change it")

    row = session.get(Role, name)
    if row is not None and row.builtin:
        raise HTTPException(status_code=403,
                            detail=f"{name!r} is part of the standard configuration "
                                   "and cannot be changed")
    try:
        role = create_role(session, name, body.rank, approves=body.approves,
                           proposes=body.proposes, manages_users=body.manages_users,
                           reads_audit=body.reads_audit,
                           sees_operations=body.sees_operations)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    SqliteSink(session).write(Record.of(
        recipe="role-changed", actor=user.id, owner=user.id,
        inputs={"approves": role.approves, "proposes": role.proposes,
                "manages_users": role.manages_users, "reads_audit": role.reads_audit,
                "sees_operations": role.sees_operations},
        output=name, subject=name))
    return authority.describe(session, name)


@router.delete("/roles/{name}")
def remove_role(name: str, session: Session = Depends(get_session),
                user: User = Depends(manages_users)):
    try:
        delete_role(session, name)
    except RoleInUse as exc:
        raise HTTPException(status_code=409,
                            detail=f"{name!r} is still assigned to a user") from exc
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    SqliteSink(session).write(Record.of(
        recipe="role-removed", actor=user.id, owner=user.id,
        inputs={}, output=name, subject=name))
    return {"status": "deleted"}
