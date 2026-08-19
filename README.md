# harness

The stack-neutral layer shared by [`python-harness`](https://github.com/jchen1707/python-harness)
and [`frontend-harness`](https://github.com/jchen1707/frontend-harness), owned in one place and
delivered two ways.

Both repos grew from one design and drifted. The same idea was being authored four times —
twice per repository, once per branch — and the drift had already produced defects: a stale
claim that Linear was reached with a personal API key, a claim that the two repos sat on
different Linear workspaces when both pointed at the same gateway, and status-sync doctrine
that existed on only one side. This repo removes the second copy so there is nothing to forget.

## Install (Claude Code)

```sh
/plugin marketplace add jchen1707/harness
```

Then enable it in a repo's `.claude/settings.json`:

```json
{ "enabledPlugins": { "harness@harness": true } }
```

## Install (Codex, and anything else)

Layer A is vendored as ordinary committed files, pinned to a commit here:

```sh
python3 /path/to/harness/scripts/vendor_sync.py sync --harness /path/to/harness --target .
```

That writes `.agents/vendor/harness/` and a `MANIFEST.json` recording the pin. Add the
freshness check to CI so the pin cannot rot silently:

```sh
python3 .../vendor_sync.py check --target . --harness /path/to/harness
```

## What is in it

| Path                           | What                                                                                                                  |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| `plugins/harness/agents/`      | Eight shared review frames — standards, spec, security, tests, simplicity, design, speed, cost — plus `explorer`      |
| `plugins/harness/commands/`    | The eight workflow commands: `/arch` `/context` `/implement-from-plan` `/lint` `/plan` `/retro` `/run` `/test`        |
| `plugins/harness/skills/`      | `full-review`, `verify`, `loop-goal`, `prune-rules`, `search-second-brain`, each with an `agents/openai.yaml` sidecar |
| `plugins/harness/workflows/`   | `full-review.js` — the fan-out runner                                                                                 |
| `plugins/harness/schema/`      | The `harness.config.json` contract                                                                                    |
| `plugins/harness/docs/agents/` | Issue tracker, triage labels, domain docs, secrets, testing and config doctrine                                       |

The unified hooks arrive in phase 5.

### Every consuming repo declares one file

Layer A never names a toolchain, a directory or a team key. It reads them from
`harness.config.json` at the consuming repository's root — the gates, the dev server, and
which reviewer checklists to compose in. `plugins/harness/schema/` is the contract and
`plugins/harness/docs/agents/config.md` is why it looks like that.

A reviewer is half a definition here and half in the stack: the frame is shared, the
checklist at `docs/agents/subagents/<agent>.md` is the stack's. `full-review.js` joins
them, and refuses to run an axis that resolves to neither.

## Both stacks are mounted here, for reading

```sh
git clone --recursive https://github.com/jchen1707/harness.git
git config submodule.recurse true    # in the clone; see below
```

`python-harness/` and `frontend-harness/` are submodules so that one clone gives you both
worlds — onboarding, cross-stack review, and a CI job that can compare the two.

**They are read-only. A stack's work is never committed through this repo.** Clone the
stack, branch there, open the PR there. Layer A does not travel this way either: it
arrives as the plugin or as a vendored tree, because `git worktree add` leaves a submodule
directory empty with no error and both stacks run worktree-per-ticket.

`git checkout` does not move a submodule's working tree, so without `submodule.recurse`
you can stand on `v2` and read the stacks' `main`. `scripts/check_submodules.py` runs on
`SessionStart` and in CI and says so when it happens.

## Branches

`v2` is authored. `main` is generated from it and must never be hand-edited. See `AGENTS.md`.
