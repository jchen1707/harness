# harness

The stack-neutral half of the agent harnesses, owned once.

This repo is **not an application, and not a harness you work inside**. It is the source of
layer A — the content that is identical in `python-harness` and `frontend-harness` — plus the
two adapters that deliver it. Nothing here runs against a product codebase.

## The rule that decides where a file goes

| Layer                  | What it is                                                                                  | Where it lives                                              |
| ---------------------- | ------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| **A — stack-neutral**  | Shared review frames, skills, commands, `full-review.js`, `docs/agents/`                    | **Here.** Generated into consumers, never edited there.     |
| **B — stack-specific** | Gates, hook config, `docs/architecture.md`, path-scoped `AGENTS.md`, each frame's checklist | `python-harness` / `frontend-harness`. Diverges on purpose. |
| **C — the product**    | An actual application                                                                       | A scaffolded product repo.                                  |

If a file states a fact true in only one stack — a team key, a directory layout, a toolchain —
it is layer B and does not belong here. Split it: the doctrine comes here, the fact stays
there and points back.

## Two delivery adapters, one source

Layer A is authored once under `plugins/harness/` and reaches consumers two ways:

| Harness                  | How layer A arrives                                                    | Worktree-safe                        |
| ------------------------ | ---------------------------------------------------------------------- | ------------------------------------ |
| Claude Code              | **Plugin** — `enabledPlugins`, resolved via `${CLAUDE_PLUGIN_ROOT}`    | Yes, the path is outside the repo    |
| Codex, and anything else | **Vendored** into `.agents/vendor/harness/` at a pinned sha, committed | Yes, they are ordinary tracked files |

A submodule would be neither. `git worktree add` leaves a submodule directory empty with no
error, and both consuming repos run worktree-per-ticket — so the shared half would be silently
missing in every ticket branch. That measurement is why the plugin exists.

Both stacks _are_ mounted here as submodules, and that is a different thing — see below.

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
├── agents/                       ← the eight shared review frames
├── commands/                     ← the eight workflow commands
├── skills/                       ← full-review, verify, loop-goal, prune-rules,
│                                    search-second-brain (+ an openai.yaml sidecar each)
├── workflows/full-review.js      ← the fan-out runner, config-driven
├── schema/                       ← harness.config.json's contract
└── docs/agents/                  ← tracker, triage, domain, secret, testing and
                                     config doctrine
scripts/vendor_sync.py            ← the second adapter: sync + freshness check
scripts/check_submodules.py       ← the submodules match the branch you are on
scripts/cross_stack.py            ← this layer A against each stack's own gates
python-harness/                   ← submodule, for reading
frontend-harness/                 ← submodule, for reading
```

## Half a definition each

A reviewer here is a **frame**: the role, the method and the reporting rules, identical in
every stack. What "in this repo's terms" means is the other half, and it lives with the
stack, at `docs/agents/subagents/<agent-name>.md`. `full-review.js` concatenates the two,
and so does the standalone subagent — the frame's first instruction is to read the
checklist.

Neither half is a review on its own, and both failures are silent. A frame with no
checklist still reviews, on nothing but general advice, and reports a confident clean. A
checklist with no frame has no reporting discipline at all. `scripts/check.py` refuses
both, and `full-review.js` throws rather than falling back to a one-line brief — a review
that quietly skipped an axis is indistinguishable from a review that found nothing.

The same split runs through the commands and skills: `/lint` does not know what a lint
command is here, it reads `harness.config.json`. See `plugins/harness/docs/agents/config.md`
for why that file has the shape it does.

## What is deliberately still layer B

- **`test-writer`.** Every other reviewer is read-only, so one `tools:` line serves both
  stacks. `test-writer` writes, and to be useful it must run the suite it wrote — which
  names a runner in its frontmatter, and a plugin ships one frontmatter. Its doctrine is
  shared at `plugins/harness/docs/agents/testing.md`; the definition stays with the stack.
- **The ninth review axis.** `async-reviewer` and `a11y-reviewer` are each that stack's
  alone. `harness.config.json` names it; `full-review.js` slots it in after `tests`.
- **What the hooks act on** — gated paths, protected files, formatters, secret variable
  names. The hooks themselves are layer A as of phase 5; what they watch is irreducibly the
  stack's, and it is declared under `hooks` in `harness.config.json`. The one exception is
  the `.env` floor in `protect_paths`, which is built in and cannot be lowered by a config.
- **The hook wiring.** Layer A ships `hooks/hooks.json` for the plugin path, addressed
  through `${CLAUDE_PLUGIN_ROOT}`. A repo that runs the vendored copy instead wires the same
  four scripts by repo-relative path in its own settings and its own Codex adapter, because
  only that repo knows where it put them.

## Changing layer A

1. Edit under `plugins/harness/` on `v2`.
2. Open a PR here. Merging republishes the plugin for every Claude Code consumer at once —
   which is the point, and also the risk. Pin by sha in a consumer's marketplace entry and
   bump deliberately.
3. Re-run `vendor_sync.py sync` in each consumer that vendors, and commit the bumped pin.
   Their CI will tell you if you forget.

The `$comment` at the top of a generated file is not decoration. A file carrying it is
overwritten without warning by the next sync.
