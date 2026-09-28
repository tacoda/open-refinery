# open-refinery — features, permissions, and the journey of a change

*Generated against 3.0.0-dev. The companion to [PLAN-3.0.md](PLAN-3.0.md): that
one says where we are going, this one says what exists and who can reach it.*

Two things to hold on to before the diagrams:

- **Authorization is a set of permissions on a person.** Roles are *presets* —
  starting points copied onto a user at creation, never read again. Where a
  preset name appears below it is shorthand for "whoever holds that set".
- **A layer is what a change is *about***: `code` · `harness` · `factory` ·
  `charter`. Almost every gate in the system keys off one.

---

## 1. Who can do what

```mermaid
flowchart LR
  subgraph P["The twelve permissions"]
    direction TB
    AC["approve:code"]:::code
    AH["approve:harness"]:::harness
    AF["approve:factory"]:::factory
    ACH["approve:charter"]:::charter
    PR["propose:*"]:::neutral
    RF["run:factory"]:::neutral
    MU["manage:users"]:::admin
    RA["read:audit"]:::admin
    SO["see:operations"]:::factory
  end

  DEV(["developer"]) --> AC & PR & RF
  LEAD(["lead"]) --> AH & ACH & PR & RF
  PLAT(["platform"]) --> AF & SO & RF
  ADMIN(["admin"]) --> MU & RA
  AUD(["auditor"]) --> RA

  classDef code fill:#dbeafe,stroke:#1e40af,color:#1e3a8a
  classDef harness fill:#dcfce7,stroke:#166534,color:#14532d
  classDef factory fill:#fef3c7,stroke:#92400e,color:#78350f
  classDef charter fill:#f3e8ff,stroke:#6b21a8,color:#581c87
  classDef admin fill:#fee2e2,stroke:#991b1b,color:#7f1d1d
  classDef neutral fill:#f1f5f9,stroke:#475569,color:#1e293b
```

**Read the gaps, not the arrows.** Three of them carry the whole design:

| Gap | Why |
|---|---|
| **admin approves nothing** | The account that grants access is not the account that approves what ships. A compromised admin can create users and read the log; it cannot merge a change or weaken a rule. |
| **lead ≠ platform** | The product is both a harness and a factory, so each gets an owner. A lead changing a prompt does not need platform; platform changing a route does not need a lead. |
| **nobody above developer approves code** | A lead reviewing a teammate's pull request holds no special authority over it. That review is a developer's job. |

`propose:*` is deliberately wide and `approve:*` is deliberately narrow. That
asymmetry is what the improve lane runs on: anyone may put a change forward,
and only the layer's owner signs it.

---

## 2. Every feature, by the permission it needs

142 routes. Grouped by what you must hold to reach them.

`propose:*` below is shorthand for all four: `propose:code`,
`propose:harness`, `propose:factory`, `propose:charter`.

### Open to any signed-in person

| Feature | Routes |
|---|---|
| Who am I, what do I hold | `GET /me` · `GET /users/{id}/permissions` (your own) |
| Read the vocabulary | `GET /permissions` · `GET /permissions/approvers/{layer}` · `GET /roles` |
| Read the shared workflow | `GET /processes` |
| Your own connections | `GET|POST|PUT|DELETE /credentials` · `GET /credentials/catalog` |
| Your own repos and work | `GET /repositories` · `GET /work-items` · `GET /metrics` |
| Approvals you are party to | `GET /approvals` · `POST /approvals/{request_id}/approve` |
| Put a change forward | `POST /proposals` · `GET /proposals` · `POST /proposals/{proposal_id}/review` |

A credential is personal: you see and manage your own, and a secret is never
returned to anyone at any permission.

### `run:factory` — doing the work

| Feature | Routes |
|---|---|
| Create work | `POST /work-items` |
| Pull tickets in from a tracker | `POST /integrations/{id}/sync` |
| Let a tracker push them in | `PUT /integrations/{id}/intake` (sets the webhook + autostart) |
| Move work along | `POST /work-items/{id}/transition` |
| Trigger a run | `POST /runs` |
| Watch runs move | `GET /runs` · the live canvas over `/ws` |
| Clear a hold | `POST /runs/{id}/approve` |

### `approve:factory` — the factory is platform's

| Feature | Routes |
|---|---|
| The stage graph | `POST /processes` |

### `approve:charter` — the standards are the lead's

| Feature | Routes |
|---|---|
| Org rules | `POST|DELETE /policies` |
| Standards packs | `POST /packs/{key}/enable` · `POST /packs/{key}/disable` |

### `see:operations` — other people's work, and the machinery

| Feature | Routes |
|---|---|
| Everyone's repos, work and runs | the same GETs, unscoped |
| Config | `GET|PUT|DELETE /settings` |
| Delivery plumbing | `/webhooks` · `/notification-rules` · `/teams` |
| Finish setup | `POST /onboarding/complete` |

### `manage:users` — admin

| Feature | Routes |
|---|---|
| Add people, set permissions | `POST /users` · `PUT /users/{id}/permissions` |
| Define presets | `PUT|DELETE /presets/{name}` |
| Who approves governance changes | `POST /approval-workflows` |

### `read:audit` — admin and the time-boxed auditor grant

| Feature | Routes |
|---|---|
| The trail | `GET /events` |
| Prove it was not altered | `GET /audit/verify` · `GET /audit/export` · `/audit/export.csv` |
| Retention | `POST /audit/purge` |
| Compliance packs | `GET /evidence` · `GET /evidence/frameworks` |
| The improve lane | `GET /improve` · `GET /improve/proposals` |
| Lend read-only access out | `/auditor-grants` |

---

## 3. The journey of a change

### 3.1 A code change — the common case

```mermaid
sequenceDiagram
  autonumber
  actor Dev as Developer
  participant API as API (the governance boundary)
  participant F as Factory
  participant H as Harness
  participant Forge
  actor Rev as Reviewer (approve:code)
  participant Audit as Audit chain

  Dev->>API: POST /runs (run:factory)
  API->>Audit: run-started
  API->>F: queue the run
  F->>F: claim a worktree
  F->>H: phase "plan"
  H-->>F: a plan
  Note over F,Rev: plan gate — cheaper to<br/>catch here than in a diff
  F->>Rev: hold for approval
  Rev-->>F: approved
  F->>H: phase "run"
  H->>Audit: one event per tool call
  H-->>F: a diff
  F->>H: phase "prove", then "review"
  H-->>F: PROVEN / VERDICT
  F->>F: delivery gate over the finished diff
  F->>Forge: open a pull request
  F->>Audit: pr-opened
  Forge-->>Rev: a human reads it
  Rev->>Forge: merge
  Note over F: nothing merges itself
```

The reviewer needs **`approve:code`** — not lead, not platform. And the run
uses **the runner's own credentials**, so the pull request is authored by the
person accountable for it.

### 3.2 A harness change — and why it is different

```mermaid
sequenceDiagram
  autonumber
  actor Dev as Developer
  participant API
  actor Lead as Lead (approve:harness)
  participant F as Factory
  participant Audit

  Dev->>API: propose a harness change (propose:harness)
  API->>Audit: proposal recorded
  Note over Dev: a developer may PROPOSE anything<br/>and APPROVE only code
  API->>Lead: awaiting the layer's owner
  Lead-->>API: approved
  API->>Audit: approval recorded
  API->>F: becomes ordinary work
  F->>F: a run, like any other
  F-->>Lead: a pull request
  Lead->>F: merge
  Note over F,Audit: the factory implements its own<br/>improvements — after two human gates
```

A `factory` change is the same picture with **platform** in the lead's place. A
`charter` change is the same with **lead** again, because the standards are
what the harness reads.

### 3.3 A ladder move — promotion and demotion are not symmetric

```mermaid
flowchart TD
  START([improve lane reads the record]) --> EV{traceable<br/>to evidence?}
  EV -->|no| DROP[dropped, not repaired]:::bad
  EV -->|yes| PROP[proposal, citing the runs]

  PROP --> DIR{direction}
  DIR -->|promotion<br/>more enforcement| PA[owner of the layer approves]
  DIR -->|demotion<br/>less enforcement| DA[owner + the full approval chain]:::warn

  PA --> BUILD[the factory implements it:<br/>writes the predicate, wires the rung]
  DA --> HUMAN[a person implements it<br/>the factory never performs a demotion]:::warn

  BUILD --> PR[pull request]
  HUMAN --> PR
  PR --> MERGE([a human merges])

  classDef bad fill:#fee2e2,stroke:#991b1b,color:#7f1d1d
  classDef warn fill:#fef3c7,stroke:#92400e,color:#78350f
```

Two rules do the work. **Evidence or it is dropped** — a lane that always finds
three things is one nobody believes by the third time. And **a demotion is the
one move that makes the system weaker**, so it never runs unattended and the
factory never carries it out itself.

---

## 4. Workflows

### 4.1 Getting started — install to first run

```mermaid
flowchart LR
  I([open-refinery init]) --> S[serve]
  S --> W[first admin<br/>signs up]
  W --> U[admin adds people<br/>preset, then edit]
  U --> C[each person connects<br/>their own keys]
  C --> P[platform picks a<br/>workflow template<br/>ship-a-ticket is already there]
  P --> T[connect a tracker,<br/>point intake at a repo]
  T --> R([Run])

  D{{open-refinery doctor<br/>says what is missing<br/>at every step}} -.-> S & C & P
```

`doctor` is the thread through all of it: nine checks, each carrying a remedy
rather than only a diagnosis. Signing up seeds `ship-a-ticket`, so there is a
workflow to run before anybody has drawn one.

Work reaches the factory three ways, and behaves the same however it arrived:

```mermaid
flowchart LR
  subgraph In[Intake]
    H[tracker webhook<br/>POST /intake/id<br/>HMAC-signed] --> WI[work item]
    Y[sync<br/>POST /integrations/id/sync] --> WI
    M[by hand<br/>POST /work-items] --> WI
  end
  WI -->|autostart on| RUN([run])
  WI -->|autostart off| Q[waits for a person]
  Q -->|POST /runs| RUN
  RUN --> WK[a worker claims it<br/>and advances one stage]
  WK --> CV[the live canvas]
```

The webhook is the one route with no bearer token — the caller is a tracker,
not a person — so the signature is the credential, and an integration with no
secret accepts nothing.

### 4.2 The default pipeline — `ship-a-ticket`

```mermaid
flowchart TD
  prepare[prepare<br/><i>claim a worktree</i>] --> plan
  plan[plan<br/><i>opus · read-only</i>] -->|approve gate| run
  run[run<br/><i>sonnet · read, write, exec</i>] --> prove
  prove[prove<br/><i>may run, may not repair</i>] --> review
  review[review<br/><i>the spec and the diff, never<br/>the run's own summary</i>] --> commit
  commit[commit<br/><i>rung 4: the delivery gate</i>] --> publish
  publish[publish<br/><i>open a pull request</i>] --> waiting

  waiting{waiting}
  waiting -->|merged| landed([landed]):::done
  waiting -->|closed| closed([closed]):::done
  waiting -->|comment| rework
  rework[rework] --> run

  run -.->|refused, max 2<br/>stop if identical| run
  commit -.->|hook refuses| run

  classDef done fill:#dcfce7,stroke:#166534,color:#14532d
```

Three things in that picture are the whole design: **deciding and building are
separate turns on different models**, **a check may run and may not repair**,
and **nothing merges itself**.

### 4.3 Oversight is a dial

```mermaid
flowchart LR
  M[manual<br/>a person answers<br/>every call] --> A[attended<br/>every write] --> S[supervised<br/>what a rule marks ask] --> AU[autonomous] --> D[dark<br/>nothing waits]

  R[["`ask` NEVER becomes `allow`.<br/>At autonomous and dark it degrades to REFUSE —<br/>an unattended factory reading ask as yes has<br/>answered a question nobody put."]]:::rule
  AU -.-> R
  D -.-> R

  classDef rule fill:#fef3c7,stroke:#92400e,color:#78350f
```

### 4.4 Where a rule is carried — the ladder

```mermaid
flowchart TD
  R0["rung 0 · prose in the charter<br/><i>sees nothing. It asks.</i>"]:::weak
  R1["rung 1 · the tool grant<br/><i>function ids, before any call</i>"]
  R2["rung 2 · a hook on the call<br/><i>the arguments, before the write lands</i>"]
  R3["rung 3 · a callback in the turn<br/><i>the call; may hold it for a person</i>"]
  R4["rung 4 · the delivery gate<br/><i>the finished diff, before the commit</i>"]
  R5["rung 5 · CI<br/><i>the merged tree, after everybody left</i>"]:::late

  R0 --> R1 --> R2 --> R3 --> R4 --> R5

  classDef weak fill:#fee2e2,stroke:#991b1b,color:#7f1d1d
  classDef late fill:#e5e7eb,stroke:#4b5563,color:#1f2937
```

**A rung is a place, not a strictness.** Rung 3 sees a call and never a diff;
rung 4 sees a diff and never the call. A rule that matters names both. And
climbing costs something — pick the cheapest rung that can actually see the
thing the rule is about.

---

## 5. The four pillars, and what exists today

```mermaid
flowchart LR
  subgraph now["Shipped"]
    AUD[audit chain<br/>keyed, verifiable]:::done
    PERM[permissions<br/>on the person]:::done
    CRED[credentials<br/>per user]:::done
    IMP[improve lane]:::done
    OPS[doctor · config · init]:::done
    GRAPH[stage graph<br/>+ canvas]:::done
    WORK[worktree + forge<br/>+ delivery gate]:::done
    HARN[the harness<br/>deepagents · phases]:::done
    QUEUE[workers<br/>claim · resume · caps]:::done
    LADDER[the ladder<br/>rungs 0·1·3·4]:::done
    IN[intake<br/>webhook · sync · by hand]:::done
  end
  subgraph next["Remaining"]
    PACKS[default pipeline packs]:::todo
    DOCS[ADOPTING · LIMITATIONS]:::todo
  end

  classDef done fill:#dcfce7,stroke:#166534,color:#14532d
  classDef todo fill:#f1f5f9,stroke:#475569,color:#1e293b
```

| Pillar | State |
|---|---|
| **1 · A software factory** | **Working end to end.** A ticket arrives by webhook, sync or hand; a run goes through the stage graph; the delivery gate opens a pull request; a comment on it becomes rework. |
| **2 · A harness** | **Working.** deepagents behind `pipeline/agent.py`, seven phases, tool grants as rung 1, `GovernanceMiddleware` as rung 3, oversight → interrupt → approval. |
| **3 · A queue of workers** | **Working.** N workers claim a run with a conditional update, advance it one stage, release it; stale claims are taken over; team caps bound concurrency; a crash resumes. |
| **4 · Business features** | **Working.** Keyed audit chain, evidence packs, the improve lane, proposals, observation, the live canvas. |

What is left before 3.0.0 is the improve lane's own pipeline, the default
workflow packs a team starts from, and the adoption docs. Sequencing is in
[PLAN-3.0.md §6](PLAN-3.0.md).
