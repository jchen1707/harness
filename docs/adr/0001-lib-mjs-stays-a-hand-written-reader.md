# 1. `lib.mjs` stays a hand-written reader, not a schema-driven one

Date: 2026-08-27

## Status

Accepted.

## Context

`harness.config.json` has three readers:

- `plugins/harness/schema/harness.config.schema.json`, the published contract.
- `scripts/config_contract.py`, which validates a config against that schema. Since
  ADR-0003's sibling change, `check.py` derives every structural rule from it rather than
  restating it in Python.
- `plugins/harness/hooks/lib.mjs`, which every hook uses to read a config at runtime. It
  hand-maintains `HOOK_DEFAULTS` and normalises a subset of the same contract.

Having removed one hand-written copy of the contract, the third looks like the obvious next
one to remove: derive `lib.mjs`'s defaults from the schema and validate there too. Any
future review of this codebase will propose it, because from the outside the two look like
the same duplication.

## Decision

`lib.mjs` stays hand-written. It does not load the schema, does not validate, and keeps its
own defaults.

## Consequences

The two readers do different jobs, and the difference is not stylistic:

- **A validator's job is to reject.** `config_contract.py` runs in a gate, where a malformed
  config must stop the build and say why.
- **A hook's job is never to reject.** `readConfig` "never throws and never reports a
  problem", because a hook that dies on a malformed config is a hook that stops enforcing,
  and one that writes to stderr on every tool call is one that gets disabled. It degrades to
  an empty config and lets each caller decide what that means — `verify` finds no gates to
  run, while `protect_paths` still applies its built-in `.env` floor.

A schema-driven `lib.mjs` would have to reproduce that tolerance on top of a validator built
to do the opposite, and it would have to do it without a JSON Schema library, since layer A
is dependency-free everywhere it runs — including in a vendored tree inside a Python repo
that no package manager has ever visited.

The accepted cost: `HOOK_DEFAULTS` can fall behind the schema. It is bounded — the keys are
the seven arrays under `hooks`, a new one is inert rather than wrong until `lib.mjs` learns
it, and `check.py` fails on a stack config the schema rejects either way.

Do not re-propose unifying these two without a reason that addresses the tolerance
requirement, not just the duplication.
