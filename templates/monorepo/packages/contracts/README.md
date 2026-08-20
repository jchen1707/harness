# contracts

`openapi.json` is the schema `apps/api` serves and `apps/web` consumes. One description, two
readers, and **neither of them writes it by hand.**

- The api **emits** it from its handlers — `uv run python scripts/emit_contract.py` — and a
  gate re-emits and compares, so a handler change that does not reach this file fails the
  api's own Definition of Done.
- The web app **generates** its types from it at install time, so a shape change the client
  has not followed is a compile error rather than a runtime surprise.

That is the whole seam, and it has no hand-written link: handler → `openapi.json` →
`types.gen.ts` → `tsc`.

## Why it matters even in one repository

In split repositories this seam is mandatory: without a published, versioned contract, two
repos hold two hand-maintained descriptions of one thing and nothing detects the drift. A
monorepo lets the build catch it instead — but only because both ends are generated. Two
hand-written mirrors in one repository drift exactly as quietly as they do in two.

## Changing it

Change the handler, run the emitter, commit both. Both apps' gates run on it, because both
name this directory in their `gatedPaths`, and both sides land in the same commit — which is
the one thing a monorepo buys that two repositories cannot.
