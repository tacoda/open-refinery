"""SQLModel table models — the ORM schema.

Expressing the schema as models (SQLModel = SQLAlchemy + Pydantic) decouples
entities from hand-written SQL and keeps other data sources (Postgres, …) within
reach. JSON columns hold a process's structure. IDs and timestamps are strings
to match the original schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def new_id() -> str:
    return uuid.uuid4().hex


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class User(SQLModel, table=True):
    __tablename__ = "users"
    id: str = Field(default_factory=new_id, primary_key=True)
    email: str = Field(unique=True, index=True)
    role: str
    pw_salt: str
    pw_hash: str
    token_hash: str = Field(unique=True, index=True)
    created_at: str = Field(default_factory=now_iso)


class Role(SQLModel, table=True):
    __tablename__ = "roles"
    name: str = Field(primary_key=True)
    rank: int = Field(index=True)  # higher = more authority / wider scope
    created_at: str = Field(default_factory=now_iso)


class UserSession(SQLModel, table=True):
    __tablename__ = "sessions"
    token_hash: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    created_at: str = Field(default_factory=now_iso)


class Repository(SQLModel, table=True):
    __tablename__ = "repositories"
    id: str = Field(default_factory=new_id, primary_key=True)
    name: str
    git_url: str = Field(unique=True, index=True)
    owner_id: str = Field(foreign_key="users.id", index=True)
    created_at: str = Field(default_factory=now_iso)


class Process(SQLModel, table=True):
    __tablename__ = "processes"
    id: str = Field(default_factory=new_id, primary_key=True)
    name: str
    archetype: str
    owner_id: str = Field(foreign_key="users.id", index=True)
    initial: str
    oversight: str = "dark"
    min_approver_role: str = "platform"  # min role to approve a gated move (risk profile)
    approval_chain: list = Field(default_factory=list, sa_column=Column(JSON))  # ordered roles; [] = [min_approver_role]
    stages: list = Field(default_factory=list, sa_column=Column(JSON))
    transitions: list = Field(default_factory=list, sa_column=Column(JSON))  # [[from, to], ...]
    gates: list = Field(default_factory=list, sa_column=Column(JSON))
    checks: dict = Field(default_factory=dict, sa_column=Column(JSON))  # {step: [check, ...]}
    created_at: str = Field(default_factory=now_iso)

    def can_transition(self, frm: str, to: str) -> bool:
        return [frm, to] in self.transitions

    def required_checks(self, to: str) -> tuple[str, ...]:
        return tuple(self.checks.get(to, ()))


class WorkItem(SQLModel, table=True):
    __tablename__ = "work_items"
    id: str = Field(default_factory=new_id, primary_key=True)
    repo_id: str = Field(foreign_key="repositories.id", index=True)
    process_id: str = Field(foreign_key="processes.id")
    title: str
    current_stage: str
    owner_id: str = Field(foreign_key="users.id", index=True)
    created_at: str = Field(default_factory=now_iso)
    external_ref: str | None = None


class Integration(SQLModel, table=True):
    __tablename__ = "integrations"
    id: str = Field(default_factory=new_id, primary_key=True)
    kind: str
    account: str
    owner_id: str = Field(foreign_key="users.id", index=True)
    secret: str
    created_at: str = Field(default_factory=now_iso)


class Target(SQLModel, table=True):
    __tablename__ = "targets"
    id: str = Field(default_factory=new_id, primary_key=True)
    name: str
    kind: str          # model | mcp | api
    endpoint: str      # model id, MCP server URL, or API base URL
    owner_id: str = Field(foreign_key="users.id", index=True)
    secret: str = ""   # encrypted JSON credential; "" when none
    output_schema: dict = Field(default_factory=dict, sa_column=Column(JSON))  # {} = free text
    created_at: str = Field(default_factory=now_iso)


class Route(SQLModel, table=True):
    __tablename__ = "routes"
    id: str = Field(default_factory=new_id, primary_key=True)
    process_id: str = Field(foreign_key="processes.id", index=True)
    step: str | None = None            # None = any step in the process
    target_id: str = Field(foreign_key="targets.id")
    priority: int = 0                  # higher wins
    owner_id: str = Field(foreign_key="users.id", index=True)
    created_at: str = Field(default_factory=now_iso)


class Quota(SQLModel, table=True):
    __tablename__ = "quotas"
    id: str = Field(default_factory=new_id, primary_key=True)
    target_id: str = Field(foreign_key="targets.id", index=True)
    limit: int                          # max units allowed
    used: int = 0                       # units consumed so far
    owner_id: str = Field(foreign_key="users.id", index=True)
    created_at: str = Field(default_factory=now_iso)


class Policy(SQLModel, table=True):
    __tablename__ = "policies"
    id: str = Field(default_factory=new_id, primary_key=True)
    kind: str = "rule"           # rule | skill | command | agent (governed harness artifact)
    effect: str                  # allow | deny (meaningful for kind=rule)
    role: str = "*"              # role this applies to, or "*"
    action: str = "*"            # e.g. "transition", "invoke", or "*"
    resource: str = "*"          # step name, target kind, or "*"
    strict: bool = False         # a lower layer may not override a strict rule
    content: str = ""            # body for skill/command/agent kinds
    owner_id: str = Field(foreign_key="users.id", index=True)
    created_at: str = Field(default_factory=now_iso)


class Invitation(SQLModel, table=True):
    __tablename__ = "invitations"
    id: str = Field(default_factory=new_id, primary_key=True)
    email: str = Field(index=True)
    role: str
    token_hash: str = Field(unique=True, index=True)
    invited_by: str = Field(foreign_key="users.id")
    expires_at: str
    status: str = Field(default="pending")  # pending | accepted | revoked
    created_at: str = Field(default_factory=now_iso)


class Setting(SQLModel, table=True):
    __tablename__ = "settings"
    key: str = Field(primary_key=True)   # e.g. "github.client_id"
    value: str                            # encrypted at rest
    updated_by: str = Field(foreign_key="users.id")
    updated_at: str = Field(default_factory=now_iso)


class ConnectState(SQLModel, table=True):
    __tablename__ = "connect_states"
    state: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="users.id")
    kind: str
    created_at: str = Field(default_factory=now_iso)


class Event(SQLModel, table=True):
    __tablename__ = "events"
    artifact_id: str = Field(primary_key=True)
    recipe: str = Field(index=True)
    actor: str = Field(index=True)
    owner: str
    input_digest: str
    output_digest: str
    subject: str | None = Field(default=None, index=True)
    created_at: str = Field(default_factory=now_iso, index=True)


class ApprovalRequest(SQLModel, table=True):
    __tablename__ = "approval_requests"
    id: str = Field(default_factory=new_id, primary_key=True)
    work_item_id: str = Field(foreign_key="work_items.id", index=True)
    to_step: str
    requested_by: str = Field(foreign_key="users.id")
    required_roles: list = Field(default_factory=list, sa_column=Column(JSON))  # ordered chain
    approvals: list = Field(default_factory=list, sa_column=Column(JSON))       # [{role,user_id,at}]
    status: str = Field(default="pending", index=True)  # pending | applied | rejected
    created_at: str = Field(default_factory=now_iso)


class ApprovalWorkflow(SQLModel, table=True):
    """Admin-configured approval chain for governance changes at a role layer."""
    __tablename__ = "approval_workflows"
    layer: str = Field(primary_key=True)     # role name the change targets
    chain: list = Field(default_factory=list, sa_column=Column(JSON))  # ordered roles
    updated_by: str = Field(foreign_key="users.id")
    updated_at: str = Field(default_factory=now_iso)


class ChangeProposal(SQLModel, table=True):
    """A proposed governance change walking a layer's approval workflow."""
    __tablename__ = "change_proposals"
    id: str = Field(default_factory=new_id, primary_key=True)
    target_kind: str                          # what to change (e.g. "policy")
    action: str                               # create | update | delete
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    layer: str                                # role layer → selects the workflow
    proposed_by: str = Field(foreign_key="users.id", index=True)
    chain: list = Field(default_factory=list, sa_column=Column(JSON))   # resolved ordered roles
    decisions: list = Field(default_factory=list, sa_column=Column(JSON))  # [{role,user_id,decision,note,at}]
    current: int = 0                          # next chain slot awaiting a decision
    status: str = Field(default="pending", index=True)  # pending|accepted|denied|revising
    applied_ref: str | None = None            # id of the object created/changed on accept
    created_at: str = Field(default_factory=now_iso)


class PackState(SQLModel, table=True):
    __tablename__ = "pack_states"
    key: str = Field(primary_key=True)      # pack catalog key
    enabled: bool = False
    updated_by: str = Field(foreign_key="users.id")
    updated_at: str = Field(default_factory=now_iso)


class Standard(SQLModel, table=True):
    """A unit of guidance seeded by an enabled pack (topic reference/standard)."""
    __tablename__ = "standards"
    id: str = Field(default_factory=new_id, primary_key=True)
    pack: str = Field(index=True)           # source pack key
    topic: str
    title: str
    body: str
    owner_id: str = Field(foreign_key="users.id", index=True)
    created_at: str = Field(default_factory=now_iso)


class Experiment(SQLModel, table=True):
    """A scientific experiment at a layer: a hypothesis, a change, before/after evals."""
    __tablename__ = "experiments"
    id: str = Field(default_factory=new_id, primary_key=True)
    name: str
    hypothesis: str
    change: str                       # the change under test
    layer: str                        # project | platform | harness | charter
    status: str = Field(default="running")  # running | concluded
    owner_id: str = Field(foreign_key="users.id", index=True)
    created_at: str = Field(default_factory=now_iso)


class EvalRun(SQLModel, table=True):
    """A measured metric for an experiment, before or after the change, per round."""
    __tablename__ = "eval_runs"
    id: str = Field(default_factory=new_id, primary_key=True)
    experiment_id: str = Field(foreign_key="experiments.id", index=True)
    round: int = 1
    phase: str                        # before | after
    metric: str
    samples: list = Field(default_factory=list, sa_column=Column(JSON))
    n: int = 0
    mean: float = 0.0
    std: float = 0.0
    created_at: str = Field(default_factory=now_iso)


class Webhook(SQLModel, table=True):
    """A registered endpoint that receives HMAC-signed audit events."""
    __tablename__ = "webhooks"
    id: str = Field(default_factory=new_id, primary_key=True)
    url: str
    events: list = Field(default_factory=list, sa_column=Column(JSON))  # recipe filter; [] = all
    secret: str                       # encrypted signing secret
    active: bool = True
    last_status: int | None = None    # HTTP status of the last delivery
    last_at: str | None = None
    owner_id: str = Field(foreign_key="users.id", index=True)
    created_at: str = Field(default_factory=now_iso)


class Audit(SQLModel, table=True):
    """A recorded debt-audit run for one area — health score + findings + insights."""
    __tablename__ = "audits"
    id: str = Field(default_factory=new_id, primary_key=True)
    area: str                         # factory | harness | charter
    score: int                        # 0–100 health
    findings: list = Field(default_factory=list, sa_column=Column(JSON))
    insights: list = Field(default_factory=list, sa_column=Column(JSON))
    ran_by: str = Field(foreign_key="users.id", index=True)
    created_at: str = Field(default_factory=now_iso, index=True)


class Claim(SQLModel, table=True):
    """A stated behavior on a repo surface (charter/harness/code), and whether an
    instruction and a gate actually back it. A claim with neither is an
    *imitation surface* — reads as governed, isn't."""
    __tablename__ = "claims"
    id: str = Field(default_factory=new_id, primary_key=True)
    repo_id: str = Field(foreign_key="repositories.id", index=True)
    surface: str                      # charter | harness | code
    text: str
    has_instruction: bool = False     # a backing instruction exists (rule/skill/command/agent)
    has_gate: bool = False            # a gate/check enforces it
    owner_id: str = Field(foreign_key="users.id", index=True)
    created_at: str = Field(default_factory=now_iso)


class Attestation(SQLModel, table=True):
    __tablename__ = "attestations"
    id: str = Field(default_factory=new_id, primary_key=True)
    work_item_id: str = Field(foreign_key="work_items.id", index=True)
    check_name: str
    passed: bool
    actor_id: str = Field(foreign_key="users.id")
    created_at: str = Field(default_factory=now_iso)
