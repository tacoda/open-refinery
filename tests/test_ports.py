"""The four ports, and the contract each one keeps.

There were five seams and two of them disagreed: `/execute` knew OpenAI and a
harness turn did not, so the same target behaved differently depending on which
path reached it. These tests exist so that cannot happen again as providers are
added — each asserts the property that makes its seam a *port* rather than a
list somebody remembers to update.
"""

import pytest

from open_refinery import credentials as creds
from open_refinery import trackers as tr
from open_refinery.models_port import PROVIDERS as MODELS
from open_refinery.models_port import provider_of
from open_refinery.pipeline.forge import FORGES


# --- models -----------------------------------------------------------------

def test_every_model_provider_can_be_routed_to():
    """A provider nothing can route to is a provider nobody can use."""
    for key, provider in MODELS.items():
        assert provider.prefixes or provider.models, key


def test_every_suggested_model_routes_back_to_its_own_provider():
    """The connect screen suggests these, so picking one must reach the
    provider you picked it from."""
    for key, provider in MODELS.items():
        for model in provider.models:
            assert provider_of(model).key == key, (key, model)


def test_the_harness_keeps_no_provider_list_of_its_own():
    """The disagreement this file exists to prevent: a second provider list.
    The other one went with the pre-3.0 execution path."""
    from open_refinery.pipeline import agent

    assert not hasattr(agent, "_provider_of")


def test_a_self_hosted_provider_declares_that_it_needs_a_host():
    assert MODELS["ollama"].needs_base_url is True


def test_model_keys_are_shareable_and_nothing_else_is():
    """A model key is a billing relationship; a forge or tracker token is an
    identity, and sharing one attributes everybody's work to one person."""
    for provider in creds.PROVIDERS.values():
        if provider.family == creds.MODEL:
            continue
        assert provider.shareable is False, provider.key


# --- forges -----------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(FORGES))
def test_every_forge_answers_all_four_questions(name):
    """Open a request, read its state, read what people said, say something
    back. A driver that answers three is not a forge."""
    driver = FORGES[name]
    for question in ("open_pr", "pr_state", "comments", "say"):
        assert callable(getattr(driver, question, None)), (name, question)


@pytest.mark.parametrize("name", sorted(FORGES))
def test_every_forge_says_where_the_branch_has_to_be(name):
    """`remote` empty means nowhere — a repo with no forge has no remote, and
    the branch is already in the checkout a reviewer opens."""
    assert hasattr(FORGES[name], "remote")


def test_local_needs_no_remote():
    assert FORGES["local"].remote == ""


@pytest.mark.parametrize("url,expected", [
    ("git@github.com:a/b.git", "github"),
    ("https://gitlab.com/a/b", "gitlab"),
    ("git@bitbucket.org:a/b.git", "bitbucket"),
    ("https://codeberg.org/a/b", "gitea"),
    ("/tmp/scratch", "local"),
])
def test_a_git_url_finds_its_forge(url, expected):
    from open_refinery.pipeline.forge import for_repo
    assert for_repo(url).name == expected


def test_a_repo_can_override_the_guess():
    from open_refinery.pipeline.forge import for_repo
    assert for_repo("git@github.com:a/b.git", "local").name == "local"


# --- trackers ---------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(tr.TRACKERS))
def test_every_tracker_satisfies_the_protocol(name):
    """It used to be a dict of dicts, so "does this one list issues?" was a key
    lookup. A protocol answers it."""
    assert isinstance(tr.TRACKERS[name], tr.Tracker)


@pytest.mark.parametrize("name", sorted(tr.TRACKERS))
def test_every_tracker_can_hand_over_its_columns(name):
    """So a process can adopt the board a team already works on."""
    assert tr.has_workflow(name)


def test_an_unknown_tracker_names_the_real_ones():
    with pytest.raises(LookupError, match="linear"):
        tr.get("not-a-tracker")


# --- the catalog is derived, not repeated -----------------------------------

def test_every_model_provider_reaches_the_connect_screen():
    """The list used to be written twice and the two drifted."""
    listed = {p["key"] for p in creds.catalog(creds.MODEL)}
    assert listed == set(MODELS)


def test_every_forge_reaches_the_connect_screen():
    listed = {p["key"] for p in creds.catalog(creds.FORGE)}
    assert listed == set(FORGES)


def test_every_tracker_reaches_the_connect_screen():
    listed = {p["key"] for p in creds.catalog(creds.TRACKER)}
    assert listed == set(tr.TRACKERS)


def test_every_provider_says_what_its_credential_must_carry():
    """The Connections screen has to answer "what do I paste here" without the
    reader leaving to go and find out."""
    for provider in creds.catalog():
        assert provider["needs"], provider["key"]


def test_a_provider_that_needs_a_key_asks_for_one():
    for provider in creds.catalog():
        if provider["key"] in ("local", "ollama"):
            continue                     # these genuinely need no key
        assert provider["fields"], provider["key"]
