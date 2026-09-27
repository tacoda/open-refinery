"""Every capability has a way in.

The gap this closes: 2.15.0 deleted a router that carried **proposals, approval
workflows, packs and standards** alongside the governance view it was meant to
remove. Nothing failed, because those features are tested by driving their
modules directly — so the suite proved the code worked while the product had no
way to reach it.

A service module with no route is a feature nobody can use.
"""

import pytest

from open_refinery.web import create_app


@pytest.fixture(scope="module")
def paths():
    return set(create_app(database_url="sqlite:///:memory:").openapi()["paths"])


# One route per pillar capability. If a router is dropped, this is what says so.
REQUIRED = {
    # pillar 4 — proposals
    "proposals": "/proposals",
    "proposal review": "/proposals/{proposal_id}/review",
    "approval workflows": "/approval-workflows",
    # the standards a team starts from
    "packs": "/packs",
    "enable a pack": "/packs/{key}/enable",
    "standards": "/standards",
    # pillar 4 — audit and observation
    "audit trail": "/events",
    "verify the chain": "/audit/verify",
    "signed export": "/audit/export",
    "evidence packs": "/evidence",
    "the improve lane": "/improve",
    "improve proposals": "/improve/proposals",
    "auditor grants": "/auditor-grants",
    # permissions and people
    "add a user": "/users",
    "a user's permissions": "/users/{user_id}/permissions",
    "the permission vocabulary": "/permissions",
    "who can approve a layer": "/permissions/approvers/{layer}",
    "presets": "/presets/{name}",
    # connections
    "credentials": "/credentials",
    "what can be connected": "/credentials/catalog",
    # pillar 1 — the factory
    "pipelines": "/pipelines",
    "validate a pipeline": "/pipelines/validate",
    "export a pipeline": "/pipelines/{pipeline_id}/export",
    "the default template": "/pipelines/templates/default",
    "the action palette": "/pipelines/actions",
    "runs": "/runs",
    "one run": "/runs/{run_id}",
    "what happens next": "/runs/{run_id}/next",
    "approve a held stage": "/runs/{run_id}/approve",
    # the work
    "repositories": "/repositories",
    "processes": "/processes",
    "work items": "/work-items",
    "move a work item": "/work-items/{item_id}/transition",
    "approvals": "/approvals",
    "run a governed call": "/execute",
    # operations
    "targets": "/targets",
    "routes": "/routes",
    "quotas": "/quotas",
    "settings": "/settings",
    "policies": "/policies",
    # getting started
    "setup": "/setup",
    "health": "/health",
    "doctor's view of config": "/onboarding",
}


@pytest.mark.parametrize("capability,route", sorted(REQUIRED.items()))
def test_every_capability_is_reachable(paths, capability, route):
    assert route in paths, f"{capability} has no route — is its router registered?"


def test_no_route_survives_a_deleted_module(paths):
    """The other direction: a route pointing at something that no longer exists
    would fail at import, so building the app at all is the assertion."""
    assert len(paths) > 90


@pytest.mark.parametrize("gone", [
    "/scim/v2/Users", "/recert/campaigns", "/systems", "/invitations",
    "/work-items/{item_id}/rollback", "/governance", "/health/areas",
    "/auth/github/login", "/auth/sso/login", "/integrations/{kind}/oauth/start",
])
def test_removed_features_leave_no_dead_routes(paths, gone):
    """A route that lingers after its feature is removed is worse than no
    route: it accepts a request and does something unexpected."""
    assert gone not in paths
