"""open-refinery — a factory for producing artifacts under governance."""

from .audit import AuditSink, JsonlSink, MemorySink
from .authz import AllowAll, AllowList, Authorizer, Unauthorized
from .factory import Factory, UnknownRecipe
from .provenance import Record
from .repositories import (
    DuplicateRepository,
    Repository,
    create_repository,
    get_repository,
    import_or_get,
    list_repositories,
)
from .processes import (
    ARCHETYPES,
    Process,
    create_process,
    get_process,
    list_processes,
)
from .store import SqliteSink, connect, query_events
from .attestations import (
    AttestationFailed,
    AttestationMissing,
    attest,
    attestations_for,
)
from .integrations import (
    SOURCE_KINDS,
    TRACKER_KINDS,
    Integration,
    create_integration,
    delete_integration,
    get_integration,
    list_integrations,
    list_issues,
)
from .migrations import run_migrations
from .metrics import (
    activity_by_actor,
    event_counts,
    lead_times,
    summary,
    wip_by_stage,
)
from .oversight import LEVELS, requires_approval
from .seeds import AlreadySeeded, seed
from .work_items import (
    ApprovalRequired,
    InvalidTransition,
    UnknownWorkItem,
    WorkItem,
    create_work_item,
    find_by_external_ref,
    get_work_item,
    list_work_items,
    sync_tracker,
    transition,
)
from .users import (
    ROLES,
    DuplicateUser,
    User,
    authenticate,
    create_user,
    rotate_token,
    user_by_token,
)

__version__ = "0.3.0"

__all__ = [
    "Factory",
    "UnknownRecipe",
    "Record",
    "Authorizer",
    "AllowAll",
    "AllowList",
    "Unauthorized",
    "AuditSink",
    "MemorySink",
    "JsonlSink",
    "SqliteSink",
    "connect",
    "query_events",
    "User",
    "ROLES",
    "DuplicateUser",
    "create_user",
    "authenticate",
    "user_by_token",
    "rotate_token",
    "Repository",
    "DuplicateRepository",
    "create_repository",
    "get_repository",
    "list_repositories",
    "Process",
    "ARCHETYPES",
    "create_process",
    "get_process",
    "list_processes",
    "WorkItem",
    "InvalidTransition",
    "ApprovalRequired",
    "UnknownWorkItem",
    "create_work_item",
    "get_work_item",
    "list_work_items",
    "transition",
    "LEVELS",
    "requires_approval",
    "attest",
    "attestations_for",
    "AttestationMissing",
    "AttestationFailed",
    "summary",
    "wip_by_stage",
    "event_counts",
    "activity_by_actor",
    "lead_times",
    "seed",
    "AlreadySeeded",
    "run_migrations",
    "Integration",
    "create_integration",
    "delete_integration",
    "get_integration",
    "list_integrations",
    "list_issues",
    "SOURCE_KINDS",
    "TRACKER_KINDS",
    "sync_tracker",
    "find_by_external_ref",
    "import_or_get",
    "__version__",
]
