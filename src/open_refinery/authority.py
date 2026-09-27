"""Permissions — what a person may do, held on the person.

A user carries a set of permissions, and **that set is the only thing ever
checked**. No indirection: two people doing similar jobs can hold different
permissions without anybody inventing a role for the difference.

This is the third and last shape. It began as a rank ladder (`developer <
platform < admin`, compared with `at_least()`), which meant admin could do
everything platform could — convenient, and not a separation of duties. 2.14.5
moved the powers onto a *role*; 3.0 moves them onto the *user*.

**Presets are the defaults to build from.** `developer`, `lead`, `platform`,
`admin` and `auditor` are named bundles you *apply* when adding someone. The
preset is copied onto the user and then edited freely, and nothing reads it
again afterwards. That keeps "add the users, give them permissions" a
ten-second job without making the permission set a lie — the cost being that
editing a preset does not change anyone already created from it, which the UI
says plainly.

The split follows the product's own shape (it is both a harness and a factory):
**lead owns the harness**, **platform owns the factory**, and **admin approves
nothing** — the account that grants access is not the account that approves what
ships, so a compromised admin can create users and read the log and cannot merge
a change or weaken a rule.

Everything here **fails closed**: an absent permission is denied, an unknown
permission string is denied, and a user with an empty set can do nothing.
"""

from __future__ import annotations

# What a change is *about*. `code` is ordinary work; the other three mirror
# `policies.LAYERS`.
CODE, HARNESS, FACTORY, CHARTER = "code", "harness", "factory", "charter"
LAYERS = (CODE, HARNESS, FACTORY, CHARTER)

# The whole vocabulary. Anything not here is not a permission, and asking for it
# is denied rather than ignored.
APPROVE = tuple(f"approve:{layer}" for layer in LAYERS)
PROPOSE = tuple(f"propose:{layer}" for layer in LAYERS)
RUN_FACTORY = "run:factory"
MANAGE_USERS = "manage:users"
READ_AUDIT = "read:audit"
SEE_OPERATIONS = "see:operations"

PERMISSIONS: tuple[str, ...] = (
    *APPROVE, *PROPOSE, RUN_FACTORY, MANAGE_USERS, READ_AUDIT, SEE_OPERATIONS)

# One line each, for the permission editor. A checkbox whose meaning you have to
# guess is a checkbox that gets ticked.
DESCRIPTIONS: dict[str, str] = {
    "approve:code": "sign off a change to the code itself",
    "approve:harness": "sign off a change to how the agent runs — phases, prompts, tool grants",
    "approve:factory": "sign off a change to how work flows — the stage graph, delivery, routing",
    "approve:charter": "sign off a change to the standards agents read",
    "propose:code": "put a code change forward for someone else to sign",
    "propose:harness": "put a harness change forward",
    "propose:factory": "put a factory change forward",
    "propose:charter": "put a standards change forward",
    RUN_FACTORY: "trigger a run",
    MANAGE_USERS: "add people and set their permissions",
    READ_AUDIT: "read the audit trail",
    SEE_OPERATIONS: "see other people's work, not only your own",
}

# The presets. A team that agrees with these configures nothing.
PRESETS: dict[str, tuple[str, ...]] = {
    # Writes the code, and may put anything forward for someone else to sign.
    "developer": ("approve:code", *PROPOSE, RUN_FACTORY),
    # Owns the harness: how one turn is constrained, and the standards it reads.
    "lead": ("approve:harness", "approve:charter", *PROPOSE, RUN_FACTORY),
    # Owns the factory: how work flows, and the only role that sees all of it.
    "platform": ("approve:factory", "propose:factory", SEE_OPERATIONS, RUN_FACTORY),
    # Approves nothing, deliberately.
    "admin": (MANAGE_USERS, READ_AUDIT),
    # What a time-boxed external audit grant resolves to.
    "auditor": (READ_AUDIT,),
}

DEFAULT_PRESET = "developer"

# Ordering only, for walking an approval chain — never an authority check.
# Declared rather than derived from the order above, which put `auditor`
# (read-only) above `admin`.
RANKS: dict[str, int] = {"auditor": 0, "developer": 1, "lead": 2,
                         "platform": 3, "admin": 4}


def valid(permission: str) -> bool:
    return permission in PERMISSIONS


def clean(permissions) -> list[str]:
    """Keep only real permissions, deduped, in vocabulary order.

    An unknown string is dropped rather than stored: a permission nothing checks
    is a permission somebody believes they have.
    """
    held = set(permissions or ())
    return [p for p in PERMISSIONS if p in held]


def of_preset(name: str) -> list[str]:
    """The permissions a preset applies. Unknown preset → nothing."""
    return list(PRESETS.get(name, ()))


def has(user, permission: str) -> bool:
    """The only check. Pure — no session, no lookup, no indirection."""
    return permission in (getattr(user, "permissions", None) or ())


def may_approve(user, layer: str) -> bool:
    return layer in LAYERS and has(user, f"approve:{layer}")


def may_propose(user, layer: str) -> bool:
    return layer in LAYERS and has(user, f"propose:{layer}")


def manages_users(user) -> bool:
    return has(user, MANAGE_USERS)


def reads_audit(user) -> bool:
    return has(user, READ_AUDIT)


def sees_operations(user) -> bool:
    """Other people's operational work — not the audit trail, which is
    `reads_audit`. Keeping them apart is what stops the role that grants access
    from also watching the work."""
    return has(user, SEE_OPERATIONS)


def may_run(user) -> bool:
    return has(user, RUN_FACTORY)


def approvers_of(session, layer: str) -> list[str]:
    """Who can approve this layer — emails, for "who do I ask".

    A question the UI has to answer at the moment somebody is blocked, and the
    alternative to answering it is them asking around.
    """
    from sqlmodel import select

    from .models import User

    if layer not in LAYERS:
        return []
    need = f"approve:{layer}"
    return [u.email for u in session.exec(select(User).order_by(User.email))
            if u.active and need in (u.permissions or [])]


def catalog() -> list[dict]:
    """The vocabulary and the presets, for the permission editor."""
    return [{"permission": p, "description": DESCRIPTIONS.get(p, "")} for p in PERMISSIONS]


def describe(user) -> dict:
    held = clean(getattr(user, "permissions", None))
    return {"permissions": held, "preset": getattr(user, "role", ""), "count": len(held)}
