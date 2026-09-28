# Adopting open-refinery

The path from an empty machine to a pull request the factory opened, with the
decision each step is really asking you to make.

Read [LIMITATIONS.md](LIMITATIONS.md) first. It is short, and it is the half of
this document that says no.

---

## 1. Install and start

```bash
pip install open-refinery
open-refinery init          # writes .env (including SECRET_KEY) and the database
open-refinery serve
```

`init` generates `SECRET_KEY`. **Back it up before anything else.** It signs
session tokens and encrypts every stored secret, and losing it means every
credential in the database is unreadable — there is no recovery path, by
design.

`open-refinery doctor` at any point says what is missing and what to do about
it, rather than only what is wrong.

## 2. The first admin

Open the app and sign up. The first account is the admin, and it is the only
one created this way — after it exists, `/setup` is closed and people are added
by somebody who holds `manage:users`.

Signing up also seeds the `ship-a-ticket` workflow, so there is something to run
before anybody has drawn a graph.

## 3. People and permissions

**Permissions live on the person, not the role.** A role is a *preset* — a
starting point you copy and then edit. Changing a preset later changes nobody,
which is the point: what somebody holds is what was granted to them, visibly,
and not a consequence of a definition that moved.

The five presets, and the question each answers:

| Preset | Holds | The question it answers |
|---|---|---|
| `developer` | `approve:code`, all `propose:*`, `run:factory` | who ships code |
| `lead` | `approve:harness`, `approve:charter`, `propose:*`, `run:factory` | who signs for how the agent works |
| `platform` | `approve:factory`, `propose:factory`, `see:operations`, `run:factory` | who owns the machinery |
| `admin` | `manage:users`, `read:audit` | who adds people |
| `auditor` | `read:audit` | who reads the trail and nothing else |

The asymmetry worth understanding before you hand these out: **`propose:*` is
wide and `approve:*` is narrow.** Anyone may put a change forward; only the
owner of a layer may sign it. That is what lets a developer propose a harness
change without being able to approve their own.

Start people on a preset and edit from there. Granting `read:audit` to someone
who also acts in the system is worth a moment's thought — an actor who can see
what was recorded about them can see it before deciding what to do next.

## 4. Keys

**Every external service is connected per user, in their own settings.** There
is no org-wide model key by default, and that is deliberate: cost, rate limits
and blame all attach to a person rather than to a shared account nobody owns.

Each person connects what they need:

- **a model provider** — Anthropic, OpenAI, Google, Mistral, DeepSeek, Groq,
  OpenRouter, Azure OpenAI, or a local Ollama
- **a code forge** — GitHub, GitLab, Gitea, Bitbucket, or `local` for a trial
  run with no accounts at all
- **a tracker** — GitHub Issues, GitLab Issues, Jira, Linear, Shortcut

Tokens and API keys, never OAuth. Each is verified on save and labelled with the
account it belongs to, so "which GitHub is this" has an answer.

## 5. A repository

Add the repo, and point it at a **local checkout** — the factory takes worktrees
off a clone you already have; it will not clone for you, and it refuses a
`git_url` that is not a checkout rather than creating a directory named after
it.

Per repository you set the base branch, which forge, `max_revisions`, and the
prepare / test / cleanup commands. The defaults are fine for a repo whose tests
run with no setup; the first repo that needs a setup step is why these exist.

**The charter** is the agent configuration already in the repository. The
default is `.agents` and `AGENTS.md`, and it is overridable per repo — point it
at `.claude`, `.cursorrules`, or whatever your agents already read. The factory
does not ask you to write a second copy of what you have.

## 6. A workflow

Open **Workflows**. `ship-a-ticket` is already there; three more templates are
in the gallery, and each says what it *gives up*, because a template chosen
without knowing that is a decision nobody made:

| Template | Gives up |
|---|---|
| `ship-a-ticket` | — the full loop |
| `quick-fix` | no plan, no proof, no review — the diff is the review |
| `strict` | four turns per job, two on a thinking model. It costs more |
| `docs-only` | no proof stage — there is nothing to run |

The canvas **is** the builder: what you draw is what runs. Saving writes a new
version rather than editing in place, so a change never reaches a run already
going.

Set the model on the graph, or per stage. Put `approve:` on the stages a person
should see before the run continues.

## 7. Work in

Three doors, and work behaves the same however it arrived:

- **by hand** — type a title on the Work screen
- **sync** — pull a tracker's issues on demand
- **webhook** — point the tracker at `POST /intake/{integration_id}`

For the webhook, set the repo and process the tickets should land in, then
create the signing secret. **It is shown once.** An integration with no secret
accepts nothing, which is the correct behaviour for an unauthenticated route.

`autostart` decides whether a ticket starts a run by itself. Leave it off until
you trust the workflow — a ticket that waits for a person is the conservative
default, and turning it on later is one switch.

## 8. Watch it

Runs advance on the server, one stage per worker tick, and survive a restart.
The **live canvas** shows the workflow you designed with the runs standing on
it; a held run is marked on its node and cleared from there.

Everything is audited. The chain is hash-linked under a key derived from
`SECRET_KEY`, checkpoints are signed, and `GET /audit/verify` recomputes it.
An auditor can be given a time-boxed grant rather than an account.

## 9. Improving it

The **improve lane** reads the audit trail and the run history and reports what
went wrong — contradictory rules, injection-shaped text, denial spikes, stages
that keep failing, revisions burned to no end, holds nobody clears.

Two rules govern it, and both matter more than the detectors:

- **Evidence or it is dropped.** Every finding names the events it came from. A
  lane that always finds three things is one nobody believes by the third time.
- **Nothing is applied.** A finding becomes a proposal; accepting a proposal
  creates a *work item*, which goes through the same stage graph and the same
  review as anything a person filed. The lane that proposes improvements does
  not get to skip the gate everything else goes through.

The single exception is a **ladder move** — where a rule is enforced, which has
no diff for a pipeline to produce. Even there the asymmetry holds: a promotion
adds enforcement and the factory may ask for one; a demotion removes it, and an
agent may not propose its own.

---

## Everything by CLI, too

The web app is the main surface, and the CLI is a peer rather than an
afterthought: `credentials`, `roles`, `pipelines`, `runs`, `phases`, `ladder`
and `packs` all drive the same API the dashboard does. Environment variables
are for the server's lifecycle only — host, port, database, secret — and
nothing an organization configures lives in one.

## When something is wrong

`open-refinery doctor` first. `open-refinery config` prints every effective
setting **and where it came from**, so "I set that" is checkable rather than
believed.
