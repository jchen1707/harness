---
description: Scaffold a new product repository — two apps, one contract, gates that dispatch by changed path
---

This creates **layer C**: a product repository, copied once and then owned by whoever it was
copied for. It is not a harness and nothing about it is shared afterwards.

## What you need first

`templates/` and `scripts/new_project.py` live in the `harness` repository, not in this
plugin and not in the vendored tree. A stack never scaffolds a product from inside itself, so
shipping a React skeleton to every consumer would be weight nobody uses — and `--agnostic`
needs a `harness` checkout regardless, because it runs `vendor_sync.py` from it.

Find one, in this order, and say which you used:

1. a path the user named;
2. `$HARNESS_REPO`, or a checkout at `~/harness`;
3. otherwise clone it — `harness` is public, so this needs no credential:
   `git clone https://github.com/jchen1707/harness ~/harness`

A fresh clone is on `main`. Scaffold from `v2` unless the user asked for the Claude-only
flavour: `git -C <harness> checkout v2`.

## Run it

```
python3 <harness>/scripts/new_project.py create <name> --api python --web react [--agnostic]
```

- `<name>` is kebab-case. It becomes a Python distribution name and an npm package name, so
  the script rejects anything that is not usable as both.
- `--into <dir>` overrides the default of `./<name>`. The directory must be empty.
- `--agnostic` vendors layer A into `.agents/vendor/harness/`, writes the Codex adapter, adds
  the freshness workflow and generates the discovery stubs. Without it, layer A arrives as
  the plugin: one line in `.claude/settings.json` and nothing in the tree.
- `--split` is not implemented, deliberately. Two repositories are only survivable with a
  published, versioned contract, and that seam is worth building against a real project's
  constraints rather than guessing at them.

## Then, before you report success

**Run each app's gates once and say what happened.** A scaffold that has never been built is
a claim, not a repository:

```
cd apps/api && uv sync && uv run pytest
cd apps/web && pnpm install && pnpm test
```

If either fails, that is the scaffold's bug and it belongs upstream in `harness` — fix it
there rather than patching the copy, or the next project inherits it.

**Tell the user about the marketplace, once per machine.** Without
`/plugin marketplace add jchen1707/harness`, the `harness@harness` entry the default flavour
writes resolves to nothing, and every shared command, agent and hook is silently absent —
which is exactly how this went wrong in both stacks before.

## What the tree means

`apps/api` and `apps/web` each carry their own `harness.config.json`, and the root one names
them under `apps`. That is what makes the gates dispatch: a turn that touched only
`apps/web/src` runs the web gates and not pytest, and a change to `packages/contracts` runs
both, because both apps name the contract in their own `gatedPaths`.

Read `plugins/harness/docs/agents/config.md` before editing any of those three files. The
rule that matters most: an app named in `apps` with no config of its own is an error, not an
empty set.

## After a vendor sync

`--agnostic` repositories carry one discovery stub per shared command and skill, so a harness
that is not Claude Code can find them. Layer A gaining a command means a stub is missing, and
nothing about that is loud. Regenerate them:

```
python3 <harness>/scripts/new_project.py stubs --target .
```
