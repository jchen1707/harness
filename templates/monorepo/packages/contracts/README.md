# contracts

The schema `apps/api` serves and `apps/web` consumes. One description, two readers.

`openapi.yaml` is the artifact. The API is its source of truth — the shapes here must match
the handlers there — and the web app should generate its types from it rather than
hand-writing a second copy.

## Why this exists even in one repository

In split repositories this seam is mandatory: without a published, versioned contract, two
repos hold two hand-maintained descriptions of one thing and nothing detects the drift. In a
monorepo the build can catch it instead — but only if the client's types are **generated**
from this file. Hand-written mirrors type-check perfectly against themselves.

## Changing it

A contract change is its own change. Both apps' gates run on it, because both name this
directory in their `gatedPaths`, and both sides land in the same commit — which is the one
thing a monorepo buys that two repositories cannot.
