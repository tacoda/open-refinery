"""Evals & experiments — run changes as experiments and test if the effect is real.

An `Experiment` states a **hypothesis**, the **change** under test, and the
**layer** it targets (project / platform / harness / charter). You record **eval**
runs — a metric measured **before** and **after** the change (per round) — and
`analyze_experiment` compares them: delta, effect size (Cohen's d), and a
significance test on the difference of means, returning a plain verdict. Iterate
by recording another round. Results are stored structured (samples + summary),
never as prose.

ponytail: the significance test is a normal-approximation z-test on the
difference of means (stdlib `statistics.NormalDist`, no scipy). Fine for
reasonable sample sizes; for small-n use a proper t-test / scipy offline.
"""

from __future__ import annotations

from statistics import NormalDist, mean, stdev

from sqlmodel import Session, select

from .models import EvalRun, Experiment, User

LAYERS = ("project", "platform", "harness", "charter")
PHASES = ("before", "after")
ALPHA = 0.05


def create_experiment(session: Session, name: str, hypothesis: str, change: str,
                      layer: str, owner_id: str) -> Experiment:
    if layer not in LAYERS:
        raise ValueError(f"unknown layer: {layer!r} (expected {LAYERS})")
    if session.get(User, owner_id) is None:
        raise ValueError(f"unknown owner: {owner_id!r}")
    exp = Experiment(name=name, hypothesis=hypothesis, change=change, layer=layer, owner_id=owner_id)
    session.add(exp)
    session.commit()
    session.refresh(exp)
    return exp


def record_eval(session: Session, experiment_id: str, phase: str, metric: str,
                samples: list[float], *, round: int = 1) -> EvalRun:
    if phase not in PHASES:
        raise ValueError(f"unknown phase: {phase!r} (expected {PHASES})")
    if session.get(Experiment, experiment_id) is None:
        raise ValueError(f"unknown experiment: {experiment_id!r}")
    vals = [float(s) for s in samples]
    if not vals:
        raise ValueError("an eval run needs at least one sample")
    run = EvalRun(experiment_id=experiment_id, round=round, phase=phase, metric=metric,
                  samples=vals, n=len(vals), mean=mean(vals),
                  std=stdev(vals) if len(vals) > 1 else 0.0)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def list_experiments(session: Session, *, layer: str | None = None) -> list[Experiment]:
    stmt = select(Experiment)
    if layer is not None:
        stmt = stmt.where(Experiment.layer == layer)
    return list(session.exec(stmt.order_by(Experiment.created_at.desc())))


def conclude_experiment(session: Session, experiment_id: str) -> Experiment:
    exp = session.get(Experiment, experiment_id)
    if exp is None:
        raise ValueError(f"unknown experiment: {experiment_id!r}")
    exp.status = "concluded"
    session.add(exp)
    session.commit()
    session.refresh(exp)
    return exp


def _significance(before: EvalRun, after: EvalRun) -> dict:
    delta = after.mean - before.mean
    se = ((before.std ** 2 / before.n) + (after.std ** 2 / after.n)) ** 0.5
    if se == 0:
        p = 0.0 if delta != 0 else 1.0
        z = float("inf") if delta != 0 else 0.0
    else:
        z = delta / se
        p = 2 * (1 - NormalDist().cdf(abs(z)))
    pooled = (((before.n - 1) * before.std ** 2 + (after.n - 1) * after.std ** 2)
              / max(1, before.n + after.n - 2)) ** 0.5
    cohen_d = delta / pooled if pooled else (float("inf") if delta else 0.0)
    significant = p < ALPHA
    if not significant:
        verdict = "no significant effect"
    elif delta > 0:
        verdict = "significant improvement"
    else:
        verdict = "significant regression"
    return {"delta": delta, "cohen_d": cohen_d, "z": z, "p_value": p,
            "significant": significant, "verdict": verdict}


def analyze_experiment(session: Session, experiment_id: str, *,
                       metric: str | None = None, round: int | None = None) -> dict:
    exp = session.get(Experiment, experiment_id)
    if exp is None:
        raise ValueError(f"unknown experiment: {experiment_id!r}")
    runs = list(session.exec(select(EvalRun).where(EvalRun.experiment_id == experiment_id)))
    if metric:
        runs = [r for r in runs if r.metric == metric]
    if round is not None:
        runs = [r for r in runs if r.round == round]

    def latest(phase: str) -> EvalRun | None:
        rs = [r for r in runs if r.phase == phase]
        return max(rs, key=lambda r: (r.round, r.created_at)) if rs else None

    before, after = latest("before"), latest("after")
    base = {"experiment_id": experiment_id, "metric": metric,
            "before": before.mean if before else None, "after": after.mean if after else None}
    if before is None or after is None:
        return {**base, "verdict": "insufficient data", "significant": False}
    return {**base, "n_before": before.n, "n_after": after.n, **_significance(before, after)}
