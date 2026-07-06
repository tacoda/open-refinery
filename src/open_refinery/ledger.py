"""Usage ledger — queryable units per governed invoke, and cost attribution.

The audit event digests its inputs (units included), so it can't be summed.
Every invoke also writes a `LedgerEntry` here; usage then rolls up by team (cost
attribution), actor, or target. "Cost" is measured in units — the same units the
executor already meters per call.
"""

from __future__ import annotations

from sqlmodel import Session, select

from .models import LedgerEntry, Target, Team, User


def record_usage(session: Session, actor_id: str, target_id: str, units: int,
                 *, subject: str | None = None, kind: str = "invoke") -> LedgerEntry:
    """Append a usage record, attributing it to the actor's team (if any)."""
    actor = session.get(User, actor_id)
    team_id = actor.team_id if actor is not None else None
    entry = LedgerEntry(team_id=team_id, actor_id=actor_id, target_id=target_id,
                        units=units, kind=kind, subject=subject)
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def _rollup(session: Session, field) -> dict[str, int]:
    totals: dict[str, int] = {}
    for e in session.exec(select(LedgerEntry)):
        key = getattr(e, field) or "unassigned"
        totals[key] = totals.get(key, 0) + e.units
    return totals


def usage_by_team(session: Session) -> list[dict]:
    """Units per team (cost attribution). Unassigned users roll into 'unassigned'."""
    totals = _rollup(session, "team_id")
    names = {t.id: t.name for t in session.exec(select(Team))}
    return [{"team_id": tid, "team": names.get(tid, tid), "units": u}
            for tid, u in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)]


def usage_by_actor(session: Session) -> dict[str, int]:
    return _rollup(session, "actor_id")


def team_usage(session: Session, team_id: str) -> int:
    return sum(e.units for e in session.exec(
        select(LedgerEntry).where(LedgerEntry.team_id == team_id)))


def traffic_graph(session: Session) -> dict:
    """Cross-agent traffic graph from the ledger: who sends how much to which
    target. Nodes are actors (tagged with their team) and targets; each edge is
    an actor→target pair weighted by call count + units. The audit event digests
    the target away, so the ledger is the only source that can wire this up."""
    entries = list(session.exec(select(LedgerEntry)))
    emails = {u.id: u.email for u in session.exec(select(User))}
    team_of = {u.id: u.team_id for u in session.exec(select(User))}
    team_names = {t.id: t.name for t in session.exec(select(Team))}
    target_names = {t.id: t.name for t in session.exec(select(Target))}

    edges: dict[tuple[str, str], dict] = {}
    actors, targets = set(), set()
    for e in entries:
        actors.add(e.actor_id)
        targets.add(e.target_id)
        edge = edges.setdefault((e.actor_id, e.target_id), {"count": 0, "units": 0})
        edge["count"] += 1
        edge["units"] += e.units

    nodes = [{"id": f"actor:{a}", "type": "actor", "label": emails.get(a, a),
              "team": team_names.get(team_of.get(a), "unassigned")} for a in actors]
    nodes += [{"id": f"target:{t}", "type": "target",
               "label": target_names.get(t, t)} for t in targets]
    edge_list = [{"source": f"actor:{a}", "target": f"target:{t}", **w}
                 for (a, t), w in edges.items()]
    return {"nodes": nodes, "edges": edge_list}
