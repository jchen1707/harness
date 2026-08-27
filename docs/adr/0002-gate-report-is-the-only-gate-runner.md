# 2. `gate_report.mjs` is the only thing that decides which gates run

Date: 2026-08-27

## Status

Accepted.

## Context

"Which gates apply to this change, in which directories, and what does each result mean" is
one question with a lot of accumulated judgment behind it: `STOP_KINDS`, monorepo `apps`
dispatch, `enabled: false`, `requires` probes, per-gate opt-in assertion, and the
`unavailable`-versus-`fail` distinction.

It had five authors. `verify.mjs` owned it; `gate_report.mjs` imported it, correctly;
`cross_stack.py` re-implemented it in Python with its own `DEFAULT_KINDS` frozenset and gate
loop; and `/lint`, `/test` and the `/verify` skill each re-implemented a subset of it in
English prose.

The copies had already drifted. Four features landed in ten commits and `cross_stack.py` —
the CI job that decides whether layer A is safe to publish to both stacks — knew none of
them. A stack that switched a gate off still had it run there, and a gate whose browser was
missing was reported as a layer A regression rather than a missing environment.

`gate_report.mjs`'s own header had stated the rule since it was written: a caller "must never
re-derive which gates apply, because that would re-author `dispatch()` and `STOP_KINDS` in
Python where they would drift silently — the single failure this repository exists to
prevent." The rule was right and bound nobody, because it lived in a comment inside the file
it governed, which is the one place a Python author would never read.

## Decision

`gate_report.mjs` is the only implementation. Every caller invokes it:

| Caller         | Invocation                                                           |
| -------------- | -------------------------------------------------------------------- |
| Stop hook      | `verify.mjs`, sharing `dispatch`/`gatedChange`/`STOP_KINDS` directly |
| `/lint`        | `--kinds lint,format,types --force`                                  |
| `/test`        | `--kinds test --force`, plus `--gate <name>` for an opt-in tier      |
| `/verify`      | `--force`, plus `--gate <name>` or `--all`                           |
| cross-stack CI | `--json`, against the freshly synced vendored tree (ADR-0003)        |
| the factory    | `--json --base <ref>`                                                |

No caller reads `harness.config.json` and selects gates itself. Prose counts as a caller:
a command file that says "run every gate whose kind is X" is an implementation, and it
drifts like one.

`--kinds` and `--force` exist to serve the callers this rule absorbed. `--force` is needed
because the change filter is right for a Stop hook firing at the end of every turn and wrong
for a person who typed a command.

## Consequences

- A new gate field is taught once. Every caller gets it without being edited.
- The command files now depend on a path (`../hooks/gate_report.mjs`, relative to the command
  file, which resolves identically under both delivery adapters). That coupling is new and is
  the price.
- Rules expressible in the runner move out of prose; the prose keeps what it is uniquely good
  at and the runner cannot express — "fix only what your change introduced", "stop at the
  first failure", "paste real output", the image-consent rule.
