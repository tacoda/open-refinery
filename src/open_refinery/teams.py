"""Teams — the unit of cost attribution and concurrency capping.

A user belongs to at most one team (`User.team_id`). A team carries a
`max_concurrency` cap (0 = unlimited) enforced live at the invoke seam, and its
usage rolls up from the ledger for cost attribution.
"""

from __future__ import annotations

from sqlmodel import Session, select

from .models import Team, User


class UnknownTeam(KeyError):
    """Raised when a team id does not exist."""


def create_team(session: Session, name: str, owner_id: str, *,
                max_concurrency: int = 0) -> Team:
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")
    team = Team(name=name, owner_id=owner_id, max_concurrency=max_concurrency)
    session.add(team)
    session.commit()
    session.refresh(team)
    return team


def list_teams(session: Session) -> list[Team]:
    return list(session.exec(select(Team).order_by(Team.created_at.desc())))


def get_team(session: Session, team_id: str) -> Team | None:
    return session.get(Team, team_id)


def delete_team(session: Session, team_id: str) -> None:
    team = session.get(Team, team_id)
    if team is None:
        return
    for u in session.exec(select(User).where(User.team_id == team_id)):  # unassign members
        u.team_id = None
        session.add(u)
    session.delete(team)
    session.commit()


def set_user_team(session: Session, user_id: str, team_id: str | None) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise ValueError(f"unknown user: {user_id!r}")
    if team_id is not None and session.get(Team, team_id) is None:
        raise UnknownTeam(team_id)
    user.team_id = team_id
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
