"""Spend ceilings on model usage, in units.

Two different questions, so two different shapes:

- **How much may one run spend?** `Repository.max_run_units` — a plain number,
  compared against that run's own metered spend. It bounds the blast radius of
  a runaway ticket.
- **How much may everybody spend?** A `Budget` — a shared counter over a
  rolling window, at `org`, `team` or `repo` scope. It bounds the burn.

**Checked before a stage, charged after it.** Nothing predicts what a turn will
cost, so a ceiling cannot be enforced the way the pre-3.0 `Quota` enforced one
(refuse before consuming, because the units were known). What this does instead
is refuse the *next* stage once the ceiling is passed. The bound that holds
inside a single turn is `max_turns`, which is a turn cap and not a cost one —
`LIMITATIONS.md` says so plainly.

A run's spend is the sum of its steps' `units`, so it is derived rather than
stored: there is one number, and it is the audited one.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from .models import Budget, Repository, RunStep, User, now_iso

SCOPES = ("org", "team", "repo")


class BudgetExceeded(Exception):
    """Raised when a ceiling has already been passed. Carries the reason in the
    words a person needs to act on it — which ceiling, and by how much."""


# --- metering ---------------------------------------------------------------

def spend_of(session: Session, run_id: str) -> int:
    """What this run has cost so far, summed from its recorded steps."""
    return sum(s.units for s in session.exec(
        select(RunStep).where(RunStep.run_id == run_id)))


def spend_by_run(session: Session, *, actor_id: str | None = None) -> list[dict]:
    """Spend per run, newest first — the read side of metering."""
    from .models import Run

    stmt = select(Run)
    if actor_id is not None:
        stmt = stmt.where(Run.actor_id == actor_id)
    runs = list(session.exec(stmt.order_by(Run.created_at.desc())))
    totals = _totals_by_run(session, [r.id for r in runs])
    return [{"run_id": r.id, "repo_id": r.repo_id, "actor_id": r.actor_id,
             "stage": r.stage, "outcome": r.outcome, "units": totals.get(r.id, 0),
             "created_at": r.created_at} for r in runs]


def _totals_by_run(session: Session, run_ids: list[str]) -> dict[str, int]:
    if not run_ids:
        return {}
    totals: dict[str, int] = {}
    for s in session.exec(select(RunStep).where(RunStep.run_id.in_(run_ids))):
        totals[s.run_id] = totals.get(s.run_id, 0) + s.units
    return totals


# --- budgets ----------------------------------------------------------------

def create_budget(session: Session, scope: str, limit: int, owner_id: str, *,
                  scope_id: str = "", window_seconds: int = 0) -> Budget:
    if scope not in SCOPES:
        raise ValueError(f"unknown budget scope: {scope!r} (expected {SCOPES})")
    if scope != "org" and not scope_id:
        raise ValueError(f"a {scope} budget needs a {scope} id")
    if limit <= 0:
        raise ValueError("a budget's limit must be positive")
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")
    budget = Budget(scope=scope, scope_id=scope_id if scope != "org" else "",
                    limit=limit, owner_id=owner_id, window_seconds=max(0, window_seconds))
    session.add(budget)
    session.commit()
    session.refresh(budget)
    return budget


def list_budgets(session: Session) -> list[Budget]:
    """All of them — a ceiling is org-wide governance, not personal property."""
    return list(session.exec(select(Budget).order_by(Budget.created_at.desc())))


def delete_budget(session: Session, budget_id: str) -> None:
    budget = session.get(Budget, budget_id)
    if budget is not None:
        session.delete(budget)
        session.commit()


def _elapsed(started_iso: str, now_iso_str: str) -> float:
    return (datetime.fromisoformat(now_iso_str)
            - datetime.fromisoformat(started_iso)).total_seconds()


def _roll(budget: Budget, now: str) -> None:
    """Reset a windowed budget whose window has elapsed. Lifetime caps never
    roll, which is what `window_seconds=0` means."""
    if not budget.window_seconds:
        return
    if not budget.window_started_at or _elapsed(budget.window_started_at, now) >= budget.window_seconds:
        budget.used = 0
        budget.window_started_at = now


def budgets_for(session: Session, run) -> list[Budget]:
    """Every budget a run answers to: the org's, its repository's, and its
    actor's team's."""
    actor = session.get(User, run.actor_id)
    team_id = actor.team_id if actor else None
    out = []
    for b in list_budgets(session):
        if b.scope == "org":
            out.append(b)
        elif b.scope == "repo" and b.scope_id == run.repo_id:
            out.append(b)
        elif b.scope == "team" and team_id and b.scope_id == team_id:
            out.append(b)
    return out


def check_budget(session: Session, run) -> None:
    """Refuse if a ceiling has already been passed. Raises `BudgetExceeded`.

    Called before a stage runs, so the stage that would have spent past the
    ceiling does not start.
    """
    repo = session.get(Repository, run.repo_id)
    spent = spend_of(session, run.id)
    if repo is not None and repo.max_run_units and spent >= repo.max_run_units:
        raise BudgetExceeded(
            f"this run has spent {spent} of its {repo.max_run_units}-unit ceiling "
            f"({repo.name}). Raise the repository's max_run_units to continue.")

    now = now_iso()
    for budget in budgets_for(session, run):
        _roll(budget, now)
        if budget.used >= budget.limit:
            where = budget.scope if budget.scope == "org" else f"{budget.scope} {budget.scope_id}"
            window = (f" in the last {budget.window_seconds}s" if budget.window_seconds
                      else " (lifetime)")
            raise BudgetExceeded(
                f"the {where} budget is exhausted: {budget.used} of {budget.limit} units"
                f"{window}. Raise it or wait for the window to roll.")
    session.commit()          # persist any window that rolled


def charge(session: Session, run, units: int) -> None:
    """Record what a stage actually spent against every budget it answers to.

    After the fact, because nothing knows what a turn costs until it is over.
    The per-run ceiling is not charged here — it reads the steps, which are the
    audited record of the same number.
    """
    if units <= 0:
        return
    now = now_iso()
    for budget in budgets_for(session, run):
        _roll(budget, now)
        if not budget.window_started_at:
            budget.window_started_at = now
        budget.used += units
        session.add(budget)
    session.commit()
