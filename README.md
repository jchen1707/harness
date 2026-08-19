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

`plugins/harness/docs/agents/` — how agents work with the issue tracker, the triage label
mapping, how to consume a repo's domain documentation, and secret-handling doctrine.

Commands, reviewer agents, shared skills, `full-review.js` and the unified hooks arrive in
later phases.

## Branches

`v2` is authored. `main` is generated from it and must never be hand-edited. See `AGENTS.md`.
