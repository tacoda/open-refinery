# Architecture

open-refinery is a **factory under governance**. The unit of work is a
*production*: an actor asks the factory to run a named *recipe*; the factory
gates, runs, and records it.

## The production loop

```
produce(name, actor, owner?, **inputs)
   │
   ├─ 1. resolve recipe        (UnknownRecipe if absent)
   ├─ 2. authorize             (Unauthorized if denied)   ← authz.py
   ├─ 3. run recipe(**inputs)  → artifact
   ├─ 4. build Record          (provenance + ownership)   ← provenance.py
   ├─ 5. append to audit sink                             ← audit.py
   ├─ 6. log the event                                    ← stdlib logging
   └─ return (artifact, record)
```

Order matters: nothing is recorded or logged unless authorization passed and
the recipe ran. An unauthorized call leaves no artifact and no audit record.

## Modules

| Module          | Responsibility                                            |
|-----------------|-----------------------------------------------------------|
| `factory.py`    | Recipe registry + the production loop                     |
| `provenance.py` | `Record` (immutable) + stable SHA-256 digests of I/O      |
| `authz.py`      | `Authorizer` protocol; `AllowAll`, `AllowList`            |
| `audit.py`      | `AuditSink` protocol; `MemorySink`, `JsonlSink`           |

`Authorizer` and `AuditSink` are `typing.Protocol`s — swap implementations
without touching the factory.

## Design choices

- **Dependency-free core.** Everything above is stdlib. Dependencies join only
  when a pillar genuinely needs one.
- **Immutable records.** A `Record` is a frozen dataclass; the audit trail is
  append-only. Provenance you can't rewrite is provenance you can trust.
- **Digests, not payloads.** Records store SHA-256 of inputs/outputs, keeping
  the trail small and non-sensitive while still verifiable.

## Roadmap

- **Governance via policies** — a policy layer that constrains *what may be
  produced* (and by whom, from which inputs), evaluated in the production loop
  alongside authorization. Policies as data/code, cascading (org ▸ repo ▸
  local, outer wins).
- **Observability** — a read-model / metrics view built by replaying the audit
  trail (counts, actors, ownership, failure clusters).
- **Pluggable sinks** — SQLite, cloud logging, event stream.
- **Async recipes** and batching.
