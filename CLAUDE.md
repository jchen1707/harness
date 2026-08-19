# harness

The stack-neutral half of the agent harnesses, owned once.

This repo is **not an application, and not a harness you work inside**. It is the source of
layer A — the content that is identical in `python-harness` and `frontend-harness` — plus the
two adapters that deliver it. Nothing here runs against a product codebase.

## The rule that decides where a file goes

| Layer | What it is | Where it lives |
| --- | --- | --- |
| **A — stack-neutral** | Shared reviewers, skills, commands, `full-review.js`, `docs/agents/` | **Here.** Generated into consumers, never edited there. |
| **B — stack-specific** | Gates, hook config, `docs/architecture.md`, path-scoped `CLAUDE.md` | `python-harness` / `frontend-harness`. Diverges on purpose. |
| **C — the product** | An actual application | A scaffolded product repo. |

If a file states a fact true in only one stack — a team key, a directory layout, a toolchain —
it is layer B and does not belong here. Split it: the doctrine comes here, the fact stays
there and points back.

## Two delivery adapters, one source

Layer A is authored once under `plugins/harness/` and reaches consumers two ways:

| Harness | How layer A arrives | Worktree-safe |
| --- | --- | --- |
| Claude Code | **Plugin** — `enabledPlugins`, resolved via `${CLAUDE_PLUGIN_ROOT}` | Yes, the path is outside the repo |
| Codex, and anything else | **Vendored** into `.agents/vendor/harness/` at a pinned sha, committed | Yes, they are ordinary tracked files |

A submodule would be neither. `git worktree add` leaves a submodule directory empty with no
error, and both consuming repos run worktree-per-ticket — so the shared half would be silently
missing in every ticket branch. That measurement is why the plugin exists.

Both stacks *are* mounted here as submodules, and that is a different thing — see below.

Vendoring's cost is staleness, and the answer is to make staleness loud rather than to avoid
copies: the pin plus `scripts/vendor_sync.py check` in each consumer's CI reports "N commits
behind" instead of drifting quietly.

## The stacks are mounted here, for reading

```
python-harness/     ← submodule, tracks the stack's own v2 (main on the main branch)
frontend-harness/   ← submodule, tracks the stack's own v2 (main on the main branch)
```

**Read-only. Work is never committed to a stack through this repo.** Clone the stack
itself, branch there, open the PR there. Nothing here is a shortcut into either one.

What the mounting buys is the things neither stack can see from inside itself: onboarding
that hands somebody both worlds in one clone, cross-stack review, and a CI job that can
compare the two. The first thing it actually catches is `generate_main.py` — one file kept
byte-identical in three repos by hand, with nothing until now able to notice a drift.
`scripts/check.py` compares them.

Set this once, in your clone:

```sh
git submodule update --init --recursive
git config submodule.recurse true
```

The second line is the one that matters. `git checkout` does **not** move a submodule's
working tree: switch this repo from `main` to `v2` and the stacks underneath stay on the
branch they were on, silently, and you read the wrong harness's doctrine while standing on
the right one. `submodule.recurse` fixes that for whoever ran it. `scripts/check_submodules.py`
is what catches whoever did not — it runs on `SessionStart` and in CI, and you can run it by
hand any time.

Which branch the submodules track is a property of the branch you are on: `v2` reads the
stacks' `v2`, `main` reads their `main`. `.gitmodules` carries that as an agnostic/Claude
region pair like any other file, so it is one substitution in the source rather than a rule
hidden in a workflow. (Prose cannot spell the marker names out — the generator refuses a
tree where one survives, and it cannot tell an example from a real one.)

## Branches

`v2` is the only hand-authored branch. `main` is **generated** from it — the transformation
adds Claude-specific assumptions — the instruction file takes its Claude Code name, and the
plugin replaces the vendored tree — and that direction is mechanical where the reverse is not.

Never hand-edit `main`. A change authored there is lost on the next regeneration.

## Layout

```
.claude-plugin/marketplace.json   ← this repo is its own marketplace
plugins/harness/
├── .claude-plugin/plugin.json
└── docs/agents/                  ← tracker, triage, domain and secret doctrine
scripts/vendor_sync.py            ← the second adapter: sync + freshness check
scripts/check_submodules.py       ← the submodules match the branch you are on
python-harness/                   ← submodule, for reading
frontend-harness/                 ← submodule, for reading
```

## Changing layer A

1. Edit under `plugins/harness/` on `v2`.
2. Open a PR here. Merging republishes the plugin for every Claude Code consumer at once —
   which is the point, and also the risk. Pin by sha in a consumer's marketplace entry and
   bump deliberately.
3. Re-run `vendor_sync.py sync` in each consumer that vendors, and commit the bumped pin.
   Their CI will tell you if you forget.

The `$comment` at the top of a generated file is not decoration. A file carrying it is
overwritten without warning by the next sync.
