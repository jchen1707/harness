# **PROJECT**

Two applications, one repository, one commit per change that spans them.

| Path                   | What it is                                         | Read next                      |
| ---------------------- | -------------------------------------------------- | ------------------------------ |
| `apps/api/`            | the HTTP API — Python, `uv`, FastAPI               | `apps/api/AGENTS.md`           |
| `apps/web/`            | the web client — Vite, React, TypeScript           | `apps/web/AGENTS.md`           |
| `packages/contracts/`  | the schema both sides answer to                    | `packages/contracts/README.md` |
| `docs/architecture.md` | what may depend on what, and where a new file goes | `docs/architecture.md`         |

This file is a router. It carries nothing that is true of only one app — that belongs in
that app's own `AGENTS.md`, next to the code it describes, where an agent working in
`apps/web` will actually read it.

## The Definition of Done is per app

`harness.config.json` in each app declares its gates. The root config only names the apps.
A change to `apps/web` runs the web gates; a change to `packages/contracts` runs both,
because both apps name the contract in their own `gatedPaths`.

Nothing is done while its app's gates are failing. Run `/lint` and `/test` yourself rather
than waiting for the Stop gate to find it — the gate is the floor, not the workflow.

## Why one repository

A change to a request shape is one change. Here it is one branch, one commit and one CI run,
and the type error lands in the same review as the schema that caused it. In two
repositories it is two PRs in a fixed order, and the window between them is where the drift
lives.

The cost is that gates must dispatch by changed path rather than run everything, which is
what the root config's `apps` list is for.

## Worktrees are the unit of isolation

One ticket, one worktree, one branch. Layer A reaches this repository in a way that survives
`git worktree add` — as a plugin outside the tree, or as ordinary committed files under
`.agents/vendor/` — so a worktree is a complete checkout, never a half-populated one.
