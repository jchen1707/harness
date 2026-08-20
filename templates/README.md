# `templates/` — the layer C scaffolds

Layer A is shared and generated; layer B belongs to a stack. This directory is the third
thing: the starting tree for **a product repository**, which is copied once and then owned
by whoever it was copied for.

`scripts/new_project.py` applies one. `/new-project` is the command that drives the script,
and it lives in the plugin like every other command — but the templates themselves stay
here, in `harness`, and are deliberately **not vendored** into the two stacks:

- A stack never scaffolds a new product from inside itself. Vendoring these would put a
  React skeleton in a Python repository, and every edit to that skeleton would report both
  stacks' pins as stale for a change that cannot reach them. An alarm that is wrong more
  often than it is right is one people learn to ignore.
- Scaffolding already needs a `harness` checkout. `scripts/vendor_sync.py` — which
  `--agnostic` runs to install layer A into the new repo — is not vendored either, for the
  same reason: it is the tool that does the vendoring.

So the command finds a checkout (or clones one; `harness` is public and needs no
credential), and the templates travel from there.

## What is in each

| Directory    | Becomes                     | Carries                                                                                                       |
| ------------ | --------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `monorepo/`  | the repository root         | the router `AGENTS.md`, the root config, `docs/`, the contract package                                        |
| `api/`       | `apps/api/`                 | a `uv` + FastAPI skeleton, its gates, the contract emitter                                                    |
| `web/`       | `apps/web/`                 | a Vite + React + TypeScript skeleton, its gates, the contract codegen                                         |
| `contract/`  | wherever the shape keeps it | the seed OpenAPI document — one copy, placed by the scaffolder                                                |
| `split-api/` | an api repository           | `--split` only: the standalone `AGENTS.md`, its config, and the workflow that publishes the contract on a tag |
| `split-web/` | a web repository            | `--split` only: the standalone `AGENTS.md`, its config, and `contract.json` — the pinned version              |
| `plugin/`    | the repository root         | one line of settings — layer A as a plugin. The default.                                                      |
| `agnostic/`  | the repository root         | the same four hooks wired to a vendored tree, the Codex adapter and the freshness job. `--agnostic` only.     |

`plugin/` and `agnostic/` are the two delivery adapters from §06 of the plan, and exactly one
of them is ever applied. `monorepo/` and the two `split-*` overlays are the two product
shapes, and exactly one of those is applied too — the overlays are copied **over** `api/` and
`web/`, replacing the files that only make sense inside a monorepo.

## The seam, in both shapes

Neither end of the contract is written by hand, and that is the whole of why a copy of it is
allowed to exist at all:

- the api **emits** `openapi.json` from its own handlers, and a gate re-emits and compares;
- the web app **generates** its types from that document at install time, and pins the one
  value it compares against with `satisfies`.

A response shape the client has not followed is then a compile error rather than a runtime
surprise. In a monorepo both ends land in one commit. Split, the api publishes the document
on a `v*` tag and the web repo pins a version — so the drift becomes a deliberate bump that
either type-checks or does not.

## The one placeholder

`__PROJECT__` is replaced with the project name everywhere it appears, and it only ever
appears **inside a string literal, a title or prose** — never in an identifier, a path or a
piece of syntax. That is what keeps every template file real source: `templates/api` and
`templates/web` are formatted, linted and typechecked here, as they stand, before anything
is ever copied out of them.

## Editing one

Change it here and the next scaffold has it. Nothing back-propagates: a project scaffolded
last month is that project's now, and a fix that matters to it is a fix somebody applies
there. That is the difference between a scaffold and layer A, and it is the reason these two
things are delivered by different mechanisms rather than one.
