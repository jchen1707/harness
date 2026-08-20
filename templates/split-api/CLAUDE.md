# **PROJECT**-api

The HTTP API. Python, `uv`, FastAPI. A repository of its own, with a client that lives in
`__PROJECT__-web` and answers to the contract this repo publishes.

## Layout

```
src/api/main.py     the app and its routes - HTTP plumbing only
src/api/health.py   a domain function, and the shape of one
tests/              pytest, one file per module under test
scripts/            the contract emitter
contracts/          the published document - generated, never hand-edited
```

Routes stay thin. A route that contains a rule is a rule that can only be tested through
HTTP, and the suite gets slower and vaguer with every one of them.

## The contract is this repository's product

`contracts/openapi.json` is emitted from the handlers by
`uv run python scripts/emit_contract.py contracts/openapi.json`, and a gate re-emits and
compares. Change a response shape and the gate fails until the document follows; that is what
makes this repo the source of truth rather than merely the place the schema happens to live.

**Tagging publishes it.** `v*` attaches the document to a GitHub release, and the web
repository pins a version and generates its types from it. So the sequence for a breaking
change is fixed, and the order matters:

1. change the handler here, regenerate the contract, land it;
2. tag a release;
3. bump the pin in the web repository and follow the type errors.

Between 2 and 3 the two repositories disagree on purpose. That window is the cost of the
split shape, and the versioned artifact is what keeps it a known cost rather than a silent
one — the client is still compiling against the version it pinned.

## Gates

`harness.config.json` is the Definition of Done: `ruff check`, `ruff format --check`, `mypy`,
`pytest`, and the contract gate. Run them with `/lint` and `/test` rather than from memory.

`mypy` is strict and checks only the paths `pyproject.toml` names. A new top-level directory
is unchecked until it is added there, and nothing goes red to tell you.

## What not to touch

`uv.lock` is generated — `uv lock` regenerates it. `contracts/openapi.json` is generated —
the emitter regenerates it. Migrations are applied by a human, not by an agent.
