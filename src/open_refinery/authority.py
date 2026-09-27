"""Authority — what a role may do, as data rather than a position in a line.

The old model was a **total order**: `developer < platform < admin`, compared
with `at_least()`. Admin could do everything platform could, and more. That is
convenient and it is not a separation of duties — the account that grants access
was also the account that could approve what ships.

So a role carries an explicit set of powers, and the four built-ins are a
**standard configuration** rather than a limit:

| role | approves | proposes | users | audit | operations |
|---|---|---|---|---|---|
| developer | code | everything | — | own work | own work |
| lead | harness, charter | harness, charter, factory | — | — | own team |
| platform | factory | factory | — | — | org-wide |
| admin | — | — | yes | yes | users + audit |
| auditor | — | — | — | yes | — |

The split follows the product's own shape: it is both a harness and a factory,
so **lead owns the harness** (phases, prompts, tool grants, the charter turns
read) and **platform owns the factory** (the stage graph, delivery, routing,
quotas). A lead changing a prompt does not need platform; platform changing a
route does not need a lead.

Everything here **fails closed**. An unknown role, an unknown layer, or a role
row that has lost its powers grants nothing — which is the opposite of what the
rank model did, where an unknown role ranked 0 and so satisfied every minimum.
"""

from __future__ import annotations

from sqlmodel import Session

# What a change can be *about*. `policies.LAYERS` covers the three governance
# layers; `code` is ordinary work, which has no Policy rows but does have
# approvers, so authority needs a name for it.
CODE = "code"
LAYERS = (CODE, "harness", "factory", "charter")


class Powers(dict):
    """One role's authority, as a plain dict so it round-trips to JSON columns."""


def powers(*, rank: int, approves: tuple = (), proposes: tuple = (),
           manages_users: bool = False, reads_audit: bool = False,
           sees_operations: bool = False) -> Powers:
    return Powers(rank=rank, approves=list(approves), proposes=list(proposes),
                  manages_users=manages_users, reads_audit=reads_audit,
                  sees_operations=sees_operations)


# The standard configuration. A team that agrees with it configures nothing.
BUILTIN: dict[str, Powers] = {
    "developer": powers(
        rank=1,
        approves=(CODE,),
        # A developer may propose a change to anything — that is what the
        # improve lane is for — but approves only the code they write.
        proposes=(CODE, "harness", "factory", "charter"),
    ),
    "lead": powers(
        rank=2,
        approves=("harness", "charter"),
        proposes=("harness", "charter", "factory"),
    ),
    "platform": powers(
        rank=3,
        approves=("factory",),
        proposes=("factory",),
        sees_operations=True,
    ),
    # Not a person's job title — the role a time-boxed auditor grant resolves
    # to (`deps.current_user`). It existed as a bare string before this module;
    # giving it a row is what makes it visible in /roles and checkable here.
    "auditor": powers(
        rank=0,
        reads_audit=True,
    ),
    "admin": powers(
        rank=4,
        # Deliberately empty. The role that grants access does not approve what
        # ships: a compromised admin account can create users and read the log,
        # and cannot merge a change or weaken a rule.
        manages_users=True,
        reads_audit=True,
    ),
}

BUILTIN_NAMES = tuple(BUILTIN)


def _row(session: Session, role: str):
    from .models import Role
    return session.get(Role, role) if role else None


def _powers_of(session: Session, role: str) -> Powers | None:
    """A role's powers from its row, or None when the role does not exist."""
    row = _row(session, role)
    if row is None:
        return None
    return Powers(rank=row.rank, approves=list(row.approves or []),
                  proposes=list(row.proposes or []),
                  manages_users=bool(row.manages_users),
                  reads_audit=bool(row.reads_audit),
                  sees_operations=bool(row.sees_operations))


def may_approve(session: Session, role: str, layer: str) -> bool:
    """Whether `role` may approve a change to `layer`."""
    p = _powers_of(session, role)
    return bool(p and layer in p["approves"])


def may_propose(session: Session, role: str, layer: str) -> bool:
    p = _powers_of(session, role)
    return bool(p and layer in p["proposes"])


def manages_users(session: Session, role: str) -> bool:
    p = _powers_of(session, role)
    return bool(p and p["manages_users"])


def reads_audit(session: Session, role: str) -> bool:
    p = _powers_of(session, role)
    return bool(p and p["reads_audit"])


def sees_operations(session: Session, role: str) -> bool:
    """Whether the role sees other people's operational data — work items,
    runs, targets, routing. Not the audit trail, which is `reads_audit`."""
    p = _powers_of(session, role)
    return bool(p and p["sees_operations"])


def approvers_for(session: Session, layer: str) -> list[str]:
    """Every role that may approve this layer, weakest first.

    For a UI that has to answer "who do I ask", and for the delivery gate
    working out which roles a diff needs.
    """
    from sqlmodel import select

    from .models import Role
    # Name breaks a rank tie, so the list is stable between page loads.
    rows = session.exec(select(Role).order_by(Role.rank, Role.name)).all()
    return [r.name for r in rows if layer in (r.approves or [])]


def describe(session: Session, role: str) -> dict:
    """One role's authority, for the API and the dashboard."""
    p = _powers_of(session, role)
    row = _row(session, role)
    if p is None or row is None:
        return {}
    return {"name": role, "builtin": bool(row.builtin), **p}
