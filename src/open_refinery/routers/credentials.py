"""Connections — the API behind Settings → Connections.

Every route here is scoped to the **calling user**: credentials are personal, so
everyone sees and manages their own. Admin may list another user's for
oversight, and what they get is metadata — provider, account, status. A secret
is never returned by any route in this file, at any role.
"""

from fastapi import APIRouter

from .. import credentials as creds
from ..deps import *  # noqa: F401,F403
from ..web import *  # noqa: F401,F403

router = APIRouter()


@router.get("/credentials/catalog")
def credential_catalog(family: str | None = None, _: User = Depends(current_user)):
    """Connectable services: fields to ask for, where to mint the key, what
    permissions it needs. The one source the UI and the wizard both read."""
    return creds.catalog(family)


@router.post("/credentials", status_code=201)
def add_credential(body: NewCredential, session: Session = Depends(get_session),
                   user: User = Depends(current_user)):
    # Publishing an org-wide model key is an operations decision, so it is
    # platform's. Not admin's: admin manages users and reads audit, and giving
    # the account-granting role a billing key too would collapse the separation.
    if body.shared and user.role != "platform":
        raise HTTPException(status_code=403,
                            detail="only platform may publish an org-wide credential")
    try:
        row = creds.connect(session, user.id, body.provider, body.credential,
                            shared=body.shared)
    except creds.UnknownProvider as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (creds.MissingField, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # the provider refused it — say so verbatim
        raise HTTPException(status_code=400,
                            detail=f"{body.provider} rejected the credential: {exc}") from exc

    SqliteSink(session).write(Record.of(
        recipe="credential-connected", actor=user.id, owner=user.id,
        inputs={"provider": body.provider, "shared": body.shared},
        output=row.account, subject=row.id))
    return creds.public(row)


@router.get("/credentials")
def get_credentials(family: str | None = None, owner: str | None = None,
                    session: Session = Depends(get_session),
                    user: User = Depends(current_user)):
    """The caller's own credentials. Admin may pass `owner` to see someone
    else's — metadata only."""
    # Reading another person's connections is oversight, which is admin's.
    # Metadata only — no route in this file returns a secret at any role.
    scope = user.id
    if owner is not None:
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="forbidden for this role")
        scope = owner or None
    return [creds.public(r) for r in creds.list_for(session, scope, family=family)]


def _own(session, integ_id: str, user: User):
    """Fetch a credential the caller is allowed to act on.

    404 rather than 403 when it belongs to someone else: a distinct 403 would
    confirm the id exists, which is a probe this endpoint should not answer.
    """
    from ..models import Integration
    row = session.get(Integration, integ_id)
    if row is None or (row.owner_id != user.id and user.role != "admin"):
        raise HTTPException(status_code=404, detail="unknown credential")
    return row


@router.post("/credentials/{integ_id}/verify")
def verify_credential(integ_id: str, session: Session = Depends(get_session),
                      user: User = Depends(current_user)):
    """Re-check a stored credential. A key revoked upstream is invisible until
    something tries to use it — this is how the UI finds out first."""
    _own(session, integ_id, user)
    return creds.recheck(session, integ_id)


@router.put("/credentials/{integ_id}")
def rotate_credential(integ_id: str, body: RotateCredential,
                      session: Session = Depends(get_session),
                      user: User = Depends(current_user)):
    """Replace the secret in place — same id, so nothing referencing it breaks."""
    _own(session, integ_id, user)
    try:
        result = creds.rotate(session, integ_id, body.credential)
    except (creds.MissingField, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400,
                            detail=f"the replacement was rejected: {exc}") from exc

    SqliteSink(session).write(Record.of(
        recipe="credential-rotated", actor=user.id, owner=user.id,
        inputs={"provider": result["provider"]}, output="rotated", subject=integ_id))
    return result


@router.delete("/credentials/{integ_id}")
def remove_credential(integ_id: str, session: Session = Depends(get_session),
                      user: User = Depends(current_user)):
    row = _own(session, integ_id, user)
    provider = row.kind
    creds.revoke(session, integ_id)
    SqliteSink(session).write(Record.of(
        recipe="credential-revoked", actor=user.id, owner=user.id,
        inputs={"provider": provider}, output="revoked", subject=integ_id))
    return {"status": "deleted"}
