from fastapi import APIRouter

from .. import mfa, oidc
from ..deps import *  # noqa: F401,F403
from ..web import *  # noqa: F401,F403

router = APIRouter()


@router.post("/policies", status_code=201)
def add_policy(body: NewPolicy, session: Session = Depends(get_session),
               user: User = Depends(require("platform", "admin"))):
    p = create_policy(session, body.effect, user.id, role=body.role,
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
                  user: User = Depends(require("platform", "admin")), note: str = ""):
    delete_policy(session, policy_id, changed_by=user.id, note=note)
    SqliteSink(session).write(Record.of(
        recipe="policy-change", actor=user.id, owner=user.id,
        inputs={"change": "deleted"}, output="", subject=policy_id))
    return {"status": "deleted"}

# --- governance notification rules (audit stream → slack/email/webhook) ---
@router.get("/notification-rules")
def get_notification_rules(session: Session = Depends(get_session),
                           _: User = Depends(require("platform", "admin"))):
    return list_rules(session)

@router.post("/notification-rules", status_code=201)
def add_notification_rule(body: NewNotificationRule, session: Session = Depends(get_session),
                          user: User = Depends(require("platform", "admin"))):
    return create_rule(session, body.label, body.channel, body.target,
                       recipe=body.recipe, created_by=user.id)

@router.delete("/notification-rules/{rule_id}")
def remove_notification_rule(rule_id: str, session: Session = Depends(get_session),
                             _: User = Depends(require("platform", "admin"))):
    delete_rule(session, rule_id)
    return {"status": "deleted"}

@router.post("/content/scan")
def content_scan(body: ScanRequest, _: User = Depends(current_user)):
    clean, hits = scan_content(body.text)
    return {"clean": clean, "hits": hits}

@router.post("/execute")
def run_execute(body: ExecuteRequest, session: Session = Depends(get_session),
                user: User = Depends(current_user)):
    return execute(session, user.id, body.process_id, body.payload, SqliteSink(session),
                  step=body.step, work_item_id=body.work_item_id,
                  experiment_id=body.experiment_id, arm=body.arm)

# --- auth ---
def _redirect_uri(request: Request) -> str:
    return f"{base_url(request)}/auth/github/callback"

@router.post("/auth/login")
def login(body: Credentials, session: Session = Depends(get_session)):
    user = authenticate(session, body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid email or password")
    if not mfa.check(user, body.code):  # MFA enabled → a valid TOTP code is required
        raise HTTPException(status_code=401, detail="mfa_required")
    return {"token": create_session(session, user.id), "user": public_user(user)}

# --- MFA (TOTP) for local accounts; SSO logins inherit MFA from the IdP ---
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
def providers(session: Session = Depends(get_session)):
    out = {kind: oauth.is_enabled(provider_creds(session, kind)) for kind in oauth.PROVIDERS}
    cfg = oidc.config(session)
    return {**out, "sso": bool(cfg), "sso_name": cfg["name"] if cfg else ""}

# --- OIDC single sign-on ---
def _sso_redirect(request: Request) -> str:
    return f"{base_url(request)}/auth/sso/callback"

@router.get("/auth/sso/config")
def get_sso_config(session: Session = Depends(get_session), _: User = Depends(require("admin"))):
    cfg = oidc.config(session)
    return {"enabled": bool(cfg), "issuer": cfg["issuer"] if cfg else "",
            "name": cfg["name"] if cfg else ""}  # client_secret never returned

@router.post("/auth/sso/config")
def set_sso_config(body: SsoConfig, session: Session = Depends(get_session),
                   user: User = Depends(require("admin"))):
    for key in ("issuer", "client_id", "client_secret", "name"):
        value = getattr(body, key)
        if value is not None:  # only overwrite provided fields (keep the secret if omitted)
            set_setting(session, f"oidc.{key}", value, user.id)
    return {"enabled": bool(oidc.config(session))}

@router.get("/auth/sso/login")
def sso_login(request: Request, session: Session = Depends(get_session)):
    cfg = oidc.config(session)
    if not cfg:
        raise HTTPException(status_code=404, detail="sso not configured")
    endpoints = oidc.discover(cfg["issuer"])
    state = secrets.token_urlsafe(16)
    resp = RedirectResponse(oidc.authorize_url(endpoints, cfg["client_id"], _sso_redirect(request), state))
    resp.set_cookie("or_sso_state", state, httponly=True, max_age=600, samesite="lax")
    return resp

@router.get("/auth/sso/callback")
def sso_callback(request: Request, code: str = "", state: str = "",
                 session: Session = Depends(get_session)):
    cfg = oidc.config(session)
    if not cfg:
        raise HTTPException(status_code=404, detail="sso not configured")
    if not state or state != request.cookies.get("or_sso_state"):
        raise HTTPException(status_code=400, detail="sso state mismatch")
    endpoints = oidc.discover(cfg["issuer"])
    access = oidc.exchange_code(endpoints, code, _sso_redirect(request), cfg)
    email = oidc.userinfo_email(endpoints, access)
    user = user_by_email(session, email) if email else None
    if user is None:  # authenticated at the IdP but no matching account here
        return RedirectResponse(home_url(request) + "#sso_error=no-account")
    token = create_session(session, user.id)
    resp = RedirectResponse(f"{home_url(request)}#token={token}")
    resp.delete_cookie("or_sso_state")
    return resp

@router.get("/auth/github/login")
def github_login(request: Request, session: Session = Depends(get_session)):
    creds = provider_creds(session, "github")
    if not oauth.is_enabled(creds):
        raise HTTPException(status_code=404, detail="github oauth not configured")
    state = secrets.token_urlsafe(16)
    scope = oauth.PROVIDERS["github"]["login_scope"]
    resp = RedirectResponse(
        oauth.authorize_url("github", state, _redirect_uri(request), scope, creds["client_id"]))
    resp.set_cookie("or_oauth_state", state, httponly=True, max_age=600, samesite="lax")
    return resp

@router.get("/auth/github/callback")
def github_callback(request: Request, code: str = "", state: str = "",
                    session: Session = Depends(get_session)):
    creds = provider_creds(session, "github")
    if not oauth.is_enabled(creds):
        raise HTTPException(status_code=404, detail="github oauth not configured")
    if not state or state != request.cookies.get("or_oauth_state"):
        raise HTTPException(status_code=400, detail="oauth state mismatch")
    access = oauth.exchange_code("github", code, _redirect_uri(request),
                                 creds["client_id"], creds["client_secret"])
    email = oauth.primary_email(access)
    user = user_by_email(session, email) if email else None
    if user is None:
        return RedirectResponse(home_url(request) + "#oauth_error=no-account")
    token = create_session(session, user.id)
    resp = RedirectResponse(f"{home_url(request)}#token={token}")
    resp.delete_cookie("or_oauth_state")
    return resp

# --- settings (encrypted config in the DB; admin/platform) ---
@router.get("/settings")
def get_settings(session: Session = Depends(get_session),
                 _: User = Depends(require("platform", "admin"))):
    return {"keys": list_setting_keys(session)}  # values never returned

@router.put("/settings")
def put_setting(body: SettingBody, session: Session = Depends(get_session),
                user: User = Depends(require("platform", "admin"))):
    set_setting(session, body.key, body.value, user.id)
    return {"status": "saved", "key": body.key}

@router.delete("/settings/{key}")
def remove_setting(key: str, session: Session = Depends(get_session),
                   _: User = Depends(require("platform", "admin"))):
    delete_setting(session, key)
    return {"status": "deleted"}

# Serve the built dashboard last so API routes always match first.
