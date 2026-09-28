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
    # `permissions` is what is checked (see authority.py). `role` is only the
    # name of the preset this user was started from — a label kept for display
    # and for "start from", never read by an authority check.
    permissions: list = Field(default_factory=list, sa_column=Column(JSON))
    role: str
    pw_salt: str
    pw_hash: str
    token_hash: str = Field(unique=True, index=True)
    # plain indexed column, not a DB foreign key: an ALTER-added FK column can't be
    # dropped by SQLite, which would break the reversible v13 downgrade. Membership
    # integrity is enforced in `set_user_team`.
    team_id: str | None = Field(default=None, index=True)
    # harness identities: an agent (Claude Code, LangGraph, …) is a service-account
    # user governed by its role like anyone; owner_id is the person who registered it.
    kind: str = "human"                 # human | agent
    harness_kind: str | None = None     # e.g. claude-code (when kind == agent)
    owner_id: str | None = None
    # TOTP MFA for local password logins (SSO logins inherit MFA from the IdP).
    # totp_secret is encrypted at rest; mfa_enabled flips true only after confirm.
    totp_secret: str = ""
    mfa_enabled: bool = False
    # SCIM deprovisioning soft-deactivates rather than deletes (keeps audit history
    # and avoids dangling owner/actor references). Inactive users can't authenticate.
    active: bool = True
    created_at: str = Field(default_factory=now_iso)


class Team(SQLModel, table=True):
    """A group users belong to — the unit of cost attribution and concurrency cap."""
    __tablename__ = "teams"
    id: str = Field(default_factory=new_id, primary_key=True)
    name: str
    max_concurrency: int = 0            # 0 = unlimited concurrent invokes
    owner_id: str = Field(foreign_key="users.id", index=True)
    created_at: str = Field(default_factory=now_iso)



class Role(SQLModel, table=True):
    """A **preset** — a named bundle of permissions to start a person from.

    Not a role in the authorizing sense: nothing checks a preset. It is copied
    onto the user at creation, and the user's own set is what is checked from
    then on (see `authority.py`). `rank` survives only for genuine orderings,
    such as walking an approval chain.
    """
    __tablename__ = "roles"
    name: str = Field(primary_key=True)
    rank: int = Field(index=True)  # ordering only — NOT an authority check
    permissions: list = Field(default_factory=list, sa_column=Column(JSON))
    builtin: bool = False          # a shipped preset; cannot be deleted
    created_at: str = Field(default_factory=now_iso)
    # Superseded by `permissions` in 2.16.0; kept because the schema is
    # append-only. Nothing reads them. Removed in 3.1.
    approves: list = Field(default_factory=list, sa_column=Column(JSON))
    proposes: list = Field(default_factory=list, sa_column=Column(JSON))
    manages_users: bool = False
    reads_audit: bool = False
    sees_operations: bool = False


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
    integration_id: str | None = None  # explicit source integration for ingest
    # Where this repo keeps its agent configuration. Empty = the defaults
    # (.agents/, AGENTS.md, and the .claude/.cursor fallbacks — see ingest.py).
    # A team whose rules live somewhere else says so here.
    charter_paths: list = Field(default_factory=list, sa_column=Column(JSON))

    # How the factory works in THIS repository. Without these every repo gets
    # identical treatment, which fails on the first one whose tests need a
    # setup step.
    base_branch: str = "main"          # what a run branches from and targets
    forge: str = ""                    # github | gitlab | local; "" = by git URL
    max_revisions: int = 2             # ceiling on a stage's refusal loop
    max_run_units: int = 0             # ceiling on what ONE run may spend; 0 = unlimited
    prepare_cmd: str = ""              # run after the worktree is claimed
    cleanup_cmd: str = ""              # run before it is released
    test_cmd: str = ""                 # what `prove` runs, when the repo says

    # The human-in-the-loop dial for runs in this repository. It lived on
    # `Process` until 3.0, where it was the only field of that record a run
    # ever read. See oversight.LEVELS.
    oversight: str = "supervised"

    ingest_interval_hours: int = 0     # 0 = manual; >0 = auto-ingest on this cadence
    last_ingest_at: str = ""           # ISO of the last scheduled ingest
    created_at: str = Field(default_factory=now_iso)



class Pipeline(SQLModel, table=True):
    """A stage graph — the factory's shape, as rows.

    Saving writes a **new row with a higher version** rather than editing in
    place, and a `Run` pins the version it started under. So editing a pipeline
    never changes a run already in flight, and "why did this run do that" stays
    answerable months later.
    """
    __tablename__ = "pipelines"
    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True)
    version: int = Field(default=1, index=True)
    owner_id: str = Field(foreign_key="users.id", index=True)
    first: str = ""
    terminal: list = Field(default_factory=list, sa_column=Column(JSON))
    model: str = ""                    # default; a stage may override
    stages: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # Node positions for the canvas, so a graph opens how it was left rather
    # than being re-laid-out every time.
    layout: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: str = Field(default_factory=now_iso)


class Constraint(SQLModel, table=True):
    """One rule, and the rung that carries it — see `ladder.py`.

    `side` is what it does: a **constraint** withholds, a **capability** grants.
    They are the same shape because they are the same idea pointing opposite
    ways, and they join at rung 1.
    """
    __tablename__ = "constraints"
    id: str = Field(default_factory=new_id, primary_key=True)
    text: str                              # the rule, in its own words
    side: str = Field(default="constraint", index=True)
    layer: str = Field(default="code", index=True)   # code|harness|factory|charter
    rung: int = Field(default=0, index=True)
    predicate: str = ""                    # a registered predicate, for rungs 2-4
    withholds: list = Field(default_factory=list, sa_column=Column(JSON))  # rung 1
    scope: str = "*"                       # which tools / paths it applies to
    enabled: bool = True
    author_id: str | None = None
    moved_by: str | None = None            # who last changed its rung
    moved_at: str = ""
    created_at: str = Field(default_factory=now_iso)


class PhaseConfig(SQLModel, table=True):
    """A team's override of one phase — see `pipeline/phases.py`.

    Only what is set here overrides the built-in, so changing a turn cap does
    not silently clear the prompt. The tool grant is rung 1 of the ladder: a
    phase is not told not to edit, it is never handed an editor.
    """
    __tablename__ = "phase_configs"
    name: str = Field(primary_key=True)
    prompt: str = ""
    model: str = ""
    thinking: str = ""
    max_turns: int = 0                 # 0 = keep the built-in
    tools: list = Field(default_factory=list, sa_column=Column(JSON))
    subagents: bool | None = None
    updated_by: str | None = None
    updated_at: str = Field(default_factory=now_iso)


class Run(SQLModel, table=True):
    """One journey of one work item through one pipeline.

    **The row is the durable state.** A worker claims a run, advances it by
    exactly one stage, and writes back — so a crash between stages resumes
    rather than restarts, and two workers cannot take the same run.
    """
    __tablename__ = "runs"
    id: str = Field(default_factory=new_id, primary_key=True)
    work_item_id: str = Field(foreign_key="work_items.id", index=True)
    pipeline_id: str = Field(foreign_key="pipelines.id", index=True)
    pipeline_version: int = 1          # pinned: edits do not reach a live run
    repo_id: str = Field(foreign_key="repositories.id", index=True)
    actor_id: str = Field(foreign_key="users.id", index=True)

    stage: str = Field(default="", index=True)
    reason: str = ""                   # "" | revision | rework
    revisions: int = 0
    last_refusal: str = ""             # verbatim, to spot a repeat
    held: bool = Field(default=False, index=True)   # waiting on a person
    approved_at: str = ""

    document: str = ""                 # the accumulating account (markdown)
    workspace: str = ""                # worktree path, once claimed
    branch: str = ""
    pr_number: str = ""
    pr_url: str = ""
    outcome: str = ""                  # landed | closed | failed, once finished
    error: str = ""

    # Per-run overrides of the graph's opt-in / optional stages.
    opt_in: list = Field(default_factory=list, sa_column=Column(JSON))
    skip: list = Field(default_factory=list, sa_column=Column(JSON))

    # Claim, so two workers cannot take the same run.
    claimed_by: str = ""
    claimed_at: str = ""

    created_at: str = Field(default_factory=now_iso, index=True)
    updated_at: str = Field(default_factory=now_iso)


class RunStep(SQLModel, table=True):
    """Append-only: one row per stage attempt.

    The answer is stored **structured** rather than as a prose blob, so a
    downgrade is queryable — "how often did prove claim yes without evidence"
    is a question about the factory, not about one run.
    """
    __tablename__ = "run_steps"
    id: str = Field(default_factory=new_id, primary_key=True)
    run_id: str = Field(foreign_key="runs.id", index=True)
    stage: str = Field(index=True)
    phase: str = ""
    action: str = ""
    attempt: int = 1
    outcome: str = ""                  # ok | refused | error | blocked | skipped
    why: str = ""                      # why it moved where it did
    answer: dict = Field(default_factory=dict, sa_column=Column(JSON))
    units: int = 0                     # model usage, for cost attribution
    target_id: str = ""
    started_at: str = Field(default_factory=now_iso)
    finished_at: str = ""


class WorkItem(SQLModel, table=True):
    __tablename__ = "work_items"
    id: str = Field(default_factory=new_id, primary_key=True)
    repo_id: str = Field(foreign_key="repositories.id", index=True)
    title: str
    owner_id: str = Field(foreign_key="users.id", index=True)

    # Tombstones. Both carried the pre-3.0 kanban and nothing reads them now —
    # a work item's stage is derived from its runs (`work_items.stage_of`).
    # They stay because the schema freeze forbids a drop, and because on an
    # upgraded install these columns are NOT NULL with no default: removing the
    # fields would make every insert fail there. Written as "" and never read.
    process_id: str = ""
    current_stage: str = ""
    created_at: str = Field(default_factory=now_iso)
    external_ref: str | None = None



class Integration(SQLModel, table=True):
    """One person's credential for one service — model, forge or tracker.

    The single credential store (see `credentials.py`). `kind` is the provider
    key from that catalog; `secret` is the encrypted credential dict; `account`
    is whoever the credential resolved to when it was verified, which is what
    makes a stored key legible on the Connections screen.

    Credentials are personal. `shared` marks the exception an admin may publish
    for the whole org — allowed only for providers the catalog marks shareable,
    which is model keys (a billing relationship) and never a forge or tracker
    token (an identity).
    """
    __tablename__ = "integrations"
    id: str = Field(default_factory=new_id, primary_key=True)
    kind: str = Field(index=True)          # provider key: anthropic | github | jira | …
    account: str
    owner_id: str = Field(foreign_key="users.id", index=True)
    secret: str
    created_at: str = Field(default_factory=now_iso)
    last_verified_at: str = ""             # ISO of the last successful verify
    status: str = "ok"                     # ok | failing — last verify outcome
    status_detail: str = ""                # why it is failing, for the UI
    shared: bool = False                   # org-wide fallback (shareable providers only)

    # Intake: where this tracker's tickets land, and whether they start a run
    # the moment they are filed. The secret signs inbound deliveries and is
    # shown once, like every other secret here.
    webhook_secret: str = ""
    intake_repo_id: str | None = None
    intake_process_id: str | None = None
    intake_pipeline: str = ""              # "" = the newest ship-a-ticket
    autostart: bool = False





class Policy(SQLModel, table=True):
    __tablename__ = "policies"
    id: str = Field(default_factory=new_id, primary_key=True)
    kind: str = "rule"           # rule | skill | command | agent (governed harness artifact)
    effect: str                  # allow | deny (meaningful for kind=rule)
    # Who it applies to: "*" for anyone, or a **permission** the actor holds
    # (authority.PERMISSIONS). It keyed off a role name until 3.0, which meant
    # a person whose permissions had been edited away from their preset was
    # still judged by the preset.
    applies_to: str = "*"
    role: str = ""               # tombstone: the pre-3.0 role selector
    action: str = "*"            # e.g. "transition", "invoke", or "*"
    resource: str = "*"          # step name, target kind, or "*"
    strict: bool = False         # a lower layer may not override a strict rule
    layer: str = "charter"       # artifact axis: factory > harness > charter
    content: str = ""            # body for skill/command/agent kinds
    namespace: str = ""          # company/dept/team/project scope (blank = global)
    pack: str = Field(default="", index=True)  # source pack key when seeded by a pack
    owner_id: str = Field(foreign_key="users.id", index=True)
    created_at: str = Field(default_factory=now_iso)


class PolicyVersion(SQLModel, table=True):
    """Immutable change-log entry for a policy — who/when/why + a full snapshot.
    Enables point-in-time reconstruction ("what policy was in effect at T") and
    diffs between versions. Append-only; never edited."""
    __tablename__ = "policy_versions"
    id: str = Field(default_factory=new_id, primary_key=True)
    policy_id: str = Field(index=True)
    version: int = 1
    change: str = "created"          # created | updated | deleted
    # snapshot of the policy at this version
    kind: str = "rule"
    effect: str = "allow"
    applies_to: str = "*"
    role: str = ""               # tombstone, mirroring Policy
    action: str = "*"
    resource: str = "*"
    strict: bool = False
    layer: str = "charter"
    content: str = ""
    namespace: str = ""
    changed_by: str | None = None
    note: str = ""                   # why the change was made
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


class DeviceGrant(SQLModel, table=True):
    """Pending OAuth device-flow authorization for a harness. The agent starts a
    grant (gets a user_code), a human approves it in the UI (which mints the
    agent + its token), then the agent polls to collect the token. Transient —
    the raw token is held only until first poll, then cleared."""
    __tablename__ = "device_grants"
    device_code: str = Field(primary_key=True)        # the agent's secret handle
    user_code: str = Field(index=True)                # short code the human enters
    harness_kind: str
    name: str
    status: str = "pending"                           # pending | approved | consumed
    agent_id: str | None = None
    token: str | None = None                          # raw token, held until first poll
    created_at: str = Field(default_factory=now_iso)
    expires_at: str = ""


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
    # Tamper-resistant hash chain. entry_hash = HMAC(k_chain, prev_hash + canonical
    # fields), where k_chain is derived from SECRET_KEY — so recomputing the chain
    # after an edit needs a secret the database does not contain. `chain_algo`
    # records which construction signed this row: pre-2.13 installs hold unkeyed
    # "sha256" rows, which still verify, but cannot be forged forward.
    prev_hash: str = ""
    entry_hash: str = Field(default="", index=True)
    chain_algo: str = "sha256"


class AuditChainState(SQLModel, table=True):
    """Single-row running head of the audit hash chain — and its anchor.

    `signature` is an HMAC over (head, algo) with a key derived from SECRET_KEY.
    It is what stops a wholesale rewrite: an attacker can relabel every event
    row as the old unkeyed construction and recompute the lot, but the head that
    produces will not match a signature they cannot compute. Per-row hashes say
    *which* row broke; this says the chain as a whole is the one we wrote.

    Blank on installs that predate 2.13 and have written nothing since.
    """
    __tablename__ = "audit_chain_state"
    id: str = Field(default="head", primary_key=True)
    head: str = ""
    algo: str = ""
    signature: str = ""


class AuditCheckpoint(SQLModel, table=True):
    """A signed explanation for a gap in the chain.

    Retention deletes events, which leaves a hole that looks exactly like an
    attacker removing evidence — and before this table existed, deleting the
    oldest events verified clean. Every purge now writes one of these, signed
    with a key derived from SECRET_KEY, and `verify_chain` refuses any gap that
    no valid checkpoint accounts for.
    """
    __tablename__ = "audit_checkpoints"
    id: str = Field(default_factory=new_id, primary_key=True)
    kind: str = "purge"               # purge | periodic
    created_at: str = Field(default_factory=now_iso, index=True)
    head: str = ""                    # chain head at the moment of the checkpoint
    cut_to: str = ""                  # prev_hash the surviving chain now starts from
    deleted_count: int = 0
    signature: str = ""               # HMAC over the fields above


class NotificationRule(SQLModel, table=True):
    """A governance alert rule: when an audit event matches `recipe` (blank = any),
    send a message to a channel (slack / email / webhook). Turns the audit stream
    into proactive signals."""
    __tablename__ = "notification_rules"
    id: str = Field(default_factory=new_id, primary_key=True)
    label: str
    recipe: str = ""                 # match this event recipe; "" = any
    channel: str = "slack"           # slack | email | webhook
    target: str = ""                 # slack/webhook URL, or email address
    enabled: bool = True
    created_by: str | None = None
    created_at: str = Field(default_factory=now_iso)


class AuditorGrant(SQLModel, table=True):
    """A time-boxed, read-only auditor credential — browses evidence + the audit
    trail, changes nothing, and expires. Not a role; a scoped external principal."""
    __tablename__ = "auditor_grants"
    id: str = Field(default_factory=new_id, primary_key=True)
    token_hash: str = Field(unique=True, index=True)
    label: str
    expires_at: str
    created_by: str | None = None
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


class Budget(SQLModel, table=True):
    """A shared spend ceiling, in model units, over a window.

    The per-run ceiling is `Repository.max_run_units` — a plain number compared
    against one run's own spend. This is the other question: how much everybody
    together may spend, per day / hour / ever. `used` accumulates and the window
    rolls, which is the counter the pre-3.0 `Quota` carried for a call site the
    factory never used.
    """

    __tablename__ = "budgets"
    id: str = Field(default_factory=new_id, primary_key=True)
    scope: str = Field(default="org", index=True)   # org | team | repo
    scope_id: str = Field(default="", index=True)   # team/repo id; "" when scope is org
    limit: int                          # max units per window (lifetime if window_seconds=0)
    used: int = 0                       # units consumed in the current window
    window_seconds: int = 0             # rolling window length; 0 = lifetime cap
    window_started_at: str = ""         # start of the current window; "" until first use
    owner_id: str = Field(foreign_key="users.id", index=True)
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


class Job(SQLModel, table=True):
    """A background task — long work (audits, ingest) run off the request path."""
    __tablename__ = "jobs"
    id: str = Field(default_factory=new_id, primary_key=True)
    kind: str
    status: str = Field(default="pending", index=True)  # pending | running | done | failed
    result: dict = Field(default_factory=dict, sa_column=Column(JSON))
    error: str = ""
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


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



class RecertCampaign(SQLModel, table=True):
    """An access-recertification campaign: reviewers re-attest every active user's
    access/role by the due date. New table — no migration (create_all handles it)."""
    __tablename__ = "recert_campaigns"
    id: str = Field(default_factory=new_id, primary_key=True)
    name: str
    created_by: str = Field(foreign_key="users.id", index=True)
    created_at: str = Field(default_factory=now_iso)
    due_at: str = ""
    status: str = Field(default="open", index=True)  # open | closed


class RecertItem(SQLModel, table=True):
    """One user under review in a campaign. email/role are snapshotted so the
    record shows what was certified even if the account later changes."""
    __tablename__ = "recert_items"
    id: str = Field(default_factory=new_id, primary_key=True)
    campaign_id: str = Field(foreign_key="recert_campaigns.id", index=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    email: str
    role: str
    decision: str = Field(default="pending", index=True)  # pending | certified | revoked
    decided_by: str = ""
    decided_at: str = ""
    note: str = ""
