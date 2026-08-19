# apps/api

The HTTP API. Python, `uv`, FastAPI.

## Layout

```
src/api/main.py     the app and its routes - HTTP plumbing only
src/api/health.py   a domain function, and the shape of one
tests/              pytest, one file per module under test
```

Routes stay thin. A route that contains a rule is a rule that can only be tested through
HTTP, and the suite gets slower and vaguer with every one of them.

## Gates

`harness.config.json` here is the Definition of Done for this app: `ruff check`,
`ruff format --check`, `mypy` and `pytest`. Run them with `/lint` and `/test` rather than
from memory — the list in that file is the only one, and it is what the Stop gate and CI
read too.

`mypy` is strict, and it checks only the paths `pyproject.toml` names. A new top-level
directory is unchecked until it is added there, and nothing goes red to tell you.

## The contract

`packages/contracts/openapi.yaml` describes what this app serves, and this app is its source
of truth: change a response shape here and change it there, in the same commit. A change to
that file runs this app's gates as well as the web app's, because it is named in
`gatedPaths` here.

## What not to touch

`uv.lock` is generated — `uv lock` regenerates it. Migrations are applied by a human, not by
an agent.
