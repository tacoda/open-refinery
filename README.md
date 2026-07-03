# open-refinery

A factory for producing artifacts under governance. Every output carries its
**provenance**, an **owner**, and an **audit trail**; every production is
**authorized** before it runs and **logged** as it happens.

> Status: **0.1.0 — proof of concept.** The core loop (authorize → produce →
> record → audit) is real and tested. Policy-based governance, richer
> observability, and pluggable sinks are on the roadmap.

## Install

```bash
uv add open-refinery       # or: pip install open-refinery
```

## Use

```python
from open_refinery import Factory

factory = Factory()

@factory.recipe("upper")
def upper(text: str) -> str:
    return text.upper()

artifact, record = factory.produce("upper", actor="ian", text="hello")
# artifact -> "HELLO"
# record   -> Record(recipe="upper", actor="ian", owner="ian",
#                    artifact_id=..., input_digest=..., output_digest=..., created_at=...)
```

Try the demo CLI:

```bash
uv run open-refinery --actor ian --text hello
```

## Pillars

| Pillar          | Where it lives                                              |
|-----------------|-------------------------------------------------------------|
| Authorization   | `Authorizer` (`AllowAll`, `AllowList`) — checked before produce |
| Provenance      | `Record` — recipe, actor, timestamp, input/output digests   |
| Ownership       | `owner` on every record (defaults to the actor)             |
| Auditability    | `AuditSink` (`MemorySink`, `JsonlSink`) — append-only trail  |
| Logging         | stdlib `logging`, logger name `open_refinery`               |
| Observability   | *(roadmap)* read-model / metrics over the audit trail       |
| Governance      | *(roadmap)* policy layer that constrains what may be produced |

## Durable audit trail

```python
from open_refinery import Factory, JsonlSink

factory = Factory(audit=JsonlSink("audit.jsonl"))
```

Each production appends one JSON line — a replayable record of who produced
what, from which inputs, and when.

## Docker

```bash
cp .env.example .env    # set SECRET_KEY
make build              # build the image
make up                 # start (detached); make logs / make down
```

## Development

```bash
make install            # uv sync --extra dev
make test               # uv run pytest
make help               # list all tasks
```

`make` targets: `install build up down logs shell test run clean dist publish`.

See [PLAN.md](PLAN.md), [CONTRIBUTING.md](CONTRIBUTING.md), and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

[MIT](LICENSE) © Ian Johnson
