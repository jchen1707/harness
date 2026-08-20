# Architecture

## The three trees

```
apps/api/        Python. Owns the database, the domain rules and the HTTP surface.
apps/web/        TypeScript. Owns rendering, routing and client state.
packages/contracts/   The schema between them. Owned by neither, changed deliberately.
```

## What may depend on what

- `apps/api` and `apps/web` **never import each other.** They are separate runtimes; the
  only thing they share is the contract.
- Both may read `packages/contracts`. Neither may write it as a side effect of a feature —
  a contract change is its own change, with both sides updated in the same commit.
- Nothing outside `apps/api` imports its internals. The API's public surface is HTTP.

## Where a new file goes

| It is…                                      | It goes                |
| ------------------------------------------- | ---------------------- |
| a request or response shape both sides need | `packages/contracts/`  |
| a domain rule, a query, a migration         | `apps/api/src/`        |
| a component, a hook, a route                | `apps/web/src/`        |
| a fact true of one app only                 | that app's `AGENTS.md` |
| a rule about how the two fit together       | here                   |

## The contract is the seam

The API is the source of truth for the schema; the web app generates from it rather than
restating it. Two hand-maintained descriptions of one shape is the failure this layout
exists to prevent — in a monorepo it is caught by the build, and only because the generated
side is generated.

When the contract changes, both apps' gates run. That is not a coincidence: each app names
`packages/contracts` in its own `gatedPaths`, which is the whole of how the dispatch knows.

## Gates

Each app declares its own in its `harness.config.json`. There is no repository-wide gate
command, and adding one would mean deciding what "the whole repo is green" means for a
change that touched one file in one app — which is the question the dispatch already
answers better.

## CI

Not scaffolded, deliberately. Whatever runs in CI must read the gates out of each app's
`harness.config.json` rather than restate them — a gate added to the config and forgotten in
the pipeline is the ordinary failure, and it fails in the direction that looks green.

The same goes for path filters. Which paths put an app back in scope is already declared,
once, as that app's `gatedPaths`; a `paths:` filter in a workflow is a second copy of it, and
the two will disagree the first time one of them is edited alone.
