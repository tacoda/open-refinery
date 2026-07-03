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
from .work_items import (
    InvalidTransition,
    UnknownWorkItem,
    WorkItem,
    create_work_item,
    get_work_item,
    list_work_items,
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

__version__ = "0.1.0"

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
    "UnknownWorkItem",
    "create_work_item",
    "get_work_item",
    "list_work_items",
    "transition",
    "__version__",
]
