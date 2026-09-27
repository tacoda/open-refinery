"""The factory: work goes in, a pull request comes out, nothing merges itself.

Everything in this package is **pure** except where it says otherwise. The stage
machine is a function of three dicts, so every branch — a refusal, the revision
cap, an identical refusal, a contract downgrade, an optional stage, a terminal —
is testable with no agent, no git and no forge. That property is the reason the
factory is worth writing this way rather than discovering its behaviour by
sending real work through it.
"""

from .spec import (
    ACTIONS,
    TEMPLATES,
    Graph,
    GraphError,
    Stage,
    default_pipeline,
    parse,
    template,
    templates,
)

__all__ = ["ACTIONS", "TEMPLATES", "Graph", "GraphError", "Stage",
           "default_pipeline", "parse", "template", "templates"]
