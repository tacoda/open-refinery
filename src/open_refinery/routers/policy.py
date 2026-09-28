from fastapi import APIRouter

from .. import mfa
from ..deps import *  # noqa: F401,F403
from ..web import *  # noqa: F401,F403

router = APIRouter()


@router.post("/policies", status_code=201)
def add_policy(body: NewPolicy, session: Session = Depends(get_session),
               user: User = Depends(approves("charter"))):
    p = create_policy(session, body.effect, user.id, applies_to=body.applies_to,
                      action=body.action, resource=body.resource,
                      strict=body.strict, kind=body.kind, content=body.content,
                      layer=body.layer, namespace=body.namespace, note=body.note)
    SqliteSink(session).write(Record.of(  # audit + notify the policy change
        recipe="policy-change", actor=user.id, owner=user.id,
        inputs={"change": "created", "kind": p.kind}, output=p.effect, subject=p.id))
    return p

@router.get("/policies")
def get_policies(session: Session = Depends(get_session), _: User = Depends(current_user)):
    return list_policies(session)

@router.get("/policies/history")
def policy_history(policy_id: str | None = None, session: Session = Depends(get_session),
                   _: User = Depends(oversight)):
    return list_policy_versions(session, policy_id=policy_id)

@router.get("/policies/at")
def policy_at(t: str, session: Session = Depends(get_session), _: User = Depends(oversight)):
    return policies_in_effect_at(session, t)  # rule set in effect at ISO time t

@router.delete("/policies/{policy_id}")
def remove_policy(policy_id: str, session: Session = Depends(get_session),
                  user: User = Depends(sees_operations), note: str = ""):
    delete_policy(session, policy_id, changed_by=user.id, note=note)
    SqliteSink(session).write(Record.of(
        recipe="policy-change", actor=user.id, owner=user.id,
        inputs={"change": "deleted"}, output="", subject=policy_id))
    return {"status": "deleted"}

# --- governance notification rules (audit stream → slack/email/webhook) ---
@router.get("/notification-rules")
def get_notification_rules(session: Session = Depends(get_session),
                           _: User = Depends(sees_operations)):
    return list_rules(session)

@router.post("/notification-rules", status_code=201)
def add_notification_rule(body: NewNotificationRule, session: Session = Depends(get_session),
                          user: User = Depends(sees_operations)):
    return create_rule(session, body.label, body.channel, body.target,
                       recipe=body.recipe, created_by=user.id)

@router.delete("/notification-rules/{rule_id}")
def remove_notification_rule(rule_id: str, session: Session = Depends(get_session),
                             _: User = Depends(sees_operations)):
    delete_rule(session, rule_id)
    return {"status": "deleted"}

@router.post("/content/scan")
def content_scan(body: ScanRequest, _: User = Depends(current_user)):
    """Try the content filter against some text.

    `egress` picks which question is asked: the local one (secrets only, what a
    tool call is held to) or the leaving one (secrets plus personal data, what a
    pull request body is held to).
    """
    clean, hits = scan_content(body.text, egress=body.egress)
    return {"clean": clean, "hits": hits, "egress": body.egress}

# --- auth ---
# Humans: email + password (+ optional TOTP). Machines: API tokens. Services:
# keys and PATs entered per user (see credentials.py). No authorization-code
# flow exists anywhere in the product.
@router.post("/auth/login")
def login(body: Credentials, session: Session = Depends(get_session)):
    user = authenticate(session, body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid email or password")
    if not mfa.check(user, body.code):  # MFA enabled → a valid TOTP code is required
        raise HTTPException(status_code=401, detail="mfa_required")
    return {"token": create_session(session, user.id), "user": public_user(user)}

# --- MFA (TOTP) for local accounts ---
@router.get("/auth/mfa/status")
def mfa_status(user: User = Depends(current_user)):
    return {"enabled": getattr(user, "mfa_enabled", False)}  # auditor principal has none

@router.post("/auth/mfa/enroll")
def mfa_enroll(session: Session = Depends(get_session), user: User = Depends(current_user)):
    return mfa.begin_enroll(session, user)  # returns the secret + otpauth URI once

@router.post("/auth/mfa/confirm")
def mfa_confirm(body: MfaCode, session: Session = Depends(get_session),
                user: User = Depends(current_user)):
    if not mfa.confirm_enroll(session, user, body.code):
        raise HTTPException(status_code=400, detail="invalid code")
    return {"enabled": True}

@router.post("/auth/mfa/disable")
def mfa_disable(body: MfaCode, session: Session = Depends(get_session),
                user: User = Depends(current_user)):
    if not mfa.disable(session, user, body.code):
        raise HTTPException(status_code=400, detail="invalid code")
    return {"enabled": False}

@router.get("/auth/providers")
def providers():
    """What the login screen may offer. Password only — kept as an endpoint so
    the client has one shape to read rather than a special case."""
    return {"password": True, "mfa": True}

# --- settings (encrypted config in the DB; admin/platform) ---
@router.get("/settings")
def get_settings(session: Session = Depends(get_session),
                 _: User = Depends(sees_operations)):
    return {"keys": list_setting_keys(session)}  # values never returned

@router.put("/settings")
def put_setting(body: SettingBody, session: Session = Depends(get_session),
                user: User = Depends(sees_operations)):
    set_setting(session, body.key, body.value, user.id)
    return {"status": "saved", "key": body.key}

@router.delete("/settings/{key}")
def remove_setting(key: str, session: Session = Depends(get_session),
                   _: User = Depends(sees_operations)):
    delete_setting(session, key)
    return {"status": "deleted"}

# Serve the built dashboard last so API routes always match first.
