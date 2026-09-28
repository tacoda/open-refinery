"""Governance, applied per tool call.

This is what makes the factory open-refinery rather than an agent runner: every
tool a turn reaches for goes through a grant, a predicate, a filter and the audit
trail before it runs.

**No spend ceiling lives here yet.** There is no per-run budget — `max_turns` is
a turn cap, not a cost one. That is the next thing this seam needs.

Three things happen before a call runs, in this order, because each is cheaper
than the last:

1. **the grant** — rung 1, already applied when the agent was built: a tool the
   phase never got cannot be called, so there is nothing here to refuse
2. **the ladder** — rung 3: a deterministic predicate, refusing in the rule's
   own words
3. **the filter** — `scan_content`, over the call's arguments

And one thing happens after: the call is **audited**, subject-linked to the run,
whatever it returned.

A refusal is handed back to the model as a tool result rather than raised. An
exception ends the turn; a refusal the model can read is one it can work around
correctly — which is the difference between a governed agent and a broken one.

**No framework here.** `Governed` decides; `agent.py` adapts it to whatever
middleware hook the harness offers. That split is what lets these decisions be
tested without installing anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..audit import AuditSink
from ..policies import PolicyDenied, scan_content
from ..provenance import Record


@dataclass
class Governed:
    """What every tool call is wrapped in.

    Holds no session: a session bound to one long-running turn would be held
    open for minutes. It takes a factory instead and opens one per call.
    """

    session_factory: object          # () -> Session
    actor_id: str
    run_id: str
    audit: AuditSink
    target_id: str = ""
    # Filled as the turn goes, so a step can record what it cost.
    calls: int = 0
    refusals: list[str] = field(default_factory=list)
    redactions: list[str] = field(default_factory=list)

    def check(self, tool: str, args: dict) -> str:
        """"" to let the call run, or the reason it was refused."""
        self.calls += 1

        text = _stringify(args)
        clean, hits = scan_content(text)
        if hits:
            # The filter is not advisory: a call carrying a secret does not run.
            self.redactions += hits
            return (f"refused: the arguments contain {', '.join(sorted(set(hits)))}. "
                    "Secrets do not leave this machine.")

        session = self._session()
        try:
            from ..ladder import evaluate          # rung 3
            verdict = evaluate(session, tool=tool, args=args, actor_id=self.actor_id)
            if verdict.refused:
                self.refusals.append(verdict.why)
                return f"refused: {verdict.why}"
        except ImportError:
            pass                                   # the ladder lands in Phase 6
        except PolicyDenied as exc:
            self.refusals.append(str(exc))
            return f"refused: {exc}"
        finally:
            session.close()

        return ""

    def record(self, tool: str, refused: str, result: str = "") -> None:
        """One audit event per call. The run is the subject, so a run's whole
        tool history is one query."""
        self.audit.write(Record.of(
            recipe="tool-refused" if refused else "tool-call",
            actor=self.actor_id, owner=self.actor_id,
            inputs={"tool": tool, "target": self.target_id},
            output=refused or _clip(result), subject=self.run_id))

    def _session(self):
        return self.session_factory()


def _stringify(args) -> str:
    if isinstance(args, dict):
        return " ".join(_stringify(v) for v in args.values())
    if isinstance(args, (list, tuple)):
        return " ".join(_stringify(v) for v in args)
    return str(args)


def _clip(text: str, limit: int = 400) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + "…"
