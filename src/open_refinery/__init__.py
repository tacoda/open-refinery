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
from .store import SqliteSink, connect, query_events
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
    "__version__",
]
