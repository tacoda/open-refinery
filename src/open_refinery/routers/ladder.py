"""The ladder — reading it, adding to it, and moving a rule.

Reading is open: **a constraint nobody can read is one nobody can rely on**.
Authoring and moving is `approve:<layer>` — the harness is the lead's, the
factory is platform's.

Promotion and demotion are not the same request, and this file is where that
stops being a comment. A promotion adds enforcement and needs the layer's owner.
A demotion **removes** it, and needs the owner *and* a second signer — because
it is the one move that makes the system weaker.
"""

from fastapi import APIRouter
from sqlmodel import select

from .. import authority, ladder
from ..deps import *  # noqa: F401,F403
from ..models import Constraint
from ..web import *  # noqa: F401,F403

router = APIRouter()


@router.get("/ladder")
def get_ladder(session: Session = Depends(get_session), _: User = Depends(current_user)):
    """Both ladders, the rungs and what each can see, and the net grant.

    Open to anyone signed in — the whole value of writing a rule down is that
    the people it constrains can read it.
    """
    return ladder.view(session)


@router.post("/ladder", status_code=201)
def add_rule(body: NewRule, session: Session = Depends(get_session),
             user: User = Depends(current_user)):
    """Put a rule on the ladder. Needs `approve:<layer>` for its layer."""
    if not authority.may_approve(user, body.layer):
        who = authority.approvers_of(session, body.layer)
        hint = f" — ask {', '.join(who[:3])}" if who else ""
        raise HTTPException(status_code=403,
                            detail=f"you do not hold approve:{body.layer}{hint}")
    try:
        rule = ladder.add(session, body.text, layer=body.layer, rung=body.rung,
                          author_id=user.id, side=body.side,
                          predicate_name=body.predicate, withholds=body.withholds,
                          scope=body.scope)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    SqliteSink(session).write(Record.of(
        recipe="ladder-added", actor=user.id, owner=user.id,
        inputs={"rung": rule.rung, "layer": rule.layer, "side": rule.side,
                "predicate": rule.predicate},
        output=rule.text, subject=rule.id))
    return ladder._brief(rule)


@router.get("/ladder/{rule_id}/move")
def preview_move(rule_id: str, to: int, session: Session = Depends(get_session),
                 _: User = Depends(current_user)):
    """What moving this rule would mean, before anybody does it.

    Pure, so the question "what would it take to make this real?" can be asked
    freely.
    """
    try:
        planned = ladder.plan_move(session, rule_id, to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"direction": planned.direction, "from": planned.frm, "to": planned.to,
            "sees": planned.why, "needs_predicate": planned.needs_predicate,
            "needs_second_signer": planned.direction == "demotion"}


@router.post("/ladder/{rule_id}/move")
def move_rule(rule_id: str, body: MoveRule, session: Session = Depends(get_session),
              user: User = Depends(current_user)):
    """Carry a rule at a different rung.

    A **demotion** needs a second signer, named in the request and distinct from
    the caller. One person removing enforcement on their own is the thing an
    auditor asks about, and "we trusted them" is not the answer they want.
    """
    rule = session.get(Constraint, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="unknown rule")
    if not authority.may_approve(user, rule.layer):
        who = authority.approvers_of(session, rule.layer)
        hint = f" — ask {', '.join(who[:3])}" if who else ""
        raise HTTPException(status_code=403,
                            detail=f"you do not hold approve:{rule.layer}{hint}")

    planned = ladder.plan_move(session, rule_id, body.to)
    if planned.direction == "demotion":
        if not body.second_signer:
            raise HTTPException(
                status_code=400,
                detail="a demotion removes enforcement — name a second signer who "
                       f"holds approve:{rule.layer}")
        second = session.exec(
            select(User).where(User.email == body.second_signer)).first()
        if second is None or not authority.may_approve(second, rule.layer):
            raise HTTPException(
                status_code=400,
                detail=f"{body.second_signer} does not hold approve:{rule.layer}")
        if second.id == user.id:
            raise HTTPException(status_code=400,
                                detail="the second signer must be somebody else")

    try:
        moved = ladder.move(session, rule_id, body.to, approver_id=user.id,
                            predicate_name=body.predicate)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    SqliteSink(session).write(Record.of(
        recipe=f"ladder-{planned.direction}", actor=user.id, owner=user.id,
        inputs={"from": planned.frm, "to": planned.to, "layer": rule.layer,
                "second_signer": body.second_signer or ""},
        output=moved.text, subject=rule_id))
    return ladder._brief(moved)


@router.delete("/ladder/{rule_id}")
def disable_rule(rule_id: str, session: Session = Depends(get_session),
                 user: User = Depends(current_user)):
    """Turn a rule off. Disabling is a demotion in everything but name, so it
    is refused for anything mechanical — move it to rung 0 instead, which leaves
    a record of who weakened it and why."""
    rule = session.get(Constraint, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="unknown rule")
    if not authority.may_approve(user, rule.layer):
        raise HTTPException(status_code=403,
                            detail=f"you do not hold approve:{rule.layer}")
    if rule.rung > 0:
        raise HTTPException(
            status_code=400,
            detail="this rule is enforced — demote it to rung 0 first, so there "
                   "is a record of who weakened it")

    rule.enabled = False
    session.add(rule)
    session.commit()
    SqliteSink(session).write(Record.of(
        recipe="ladder-disabled", actor=user.id, owner=user.id,
        inputs={"layer": rule.layer}, output=rule.text, subject=rule_id))
    return {"status": "disabled"}
