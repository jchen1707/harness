# 3. The cross-stack job runs the layer A it just delivered

Date: 2026-08-27

## Status

Accepted. Implements ADR-0002 for `scripts/cross_stack.py`.

## Context

`cross_stack.py` answers the question no stack can ask from inside itself: does the layer A
_on this branch_ still satisfy each stack's own Definition of Done? Each stack sees layer A
only at the sha it pinned, which is by construction the last one that worked.

It already syncs the working tree's layer A into each mounted stack and verifies the synced
tree passes its own integrity check. It then had to run the stack's gates, and did so with
its own Python loop — the drift ADR-0002 describes.

Two ways to fix it: invoke `plugins/harness/hooks/gate_report.mjs` from this checkout, or
invoke `<stack>/.agents/vendor/harness/hooks/gate_report.mjs` from the tree the sync just
wrote.

## Decision

Invoke the synced vendored tree's copy.

Node is not a new dependency: both stacks declare Node 22 in `.nvmrc`, and both already
vendor _and gate_ `.agents/vendor/harness/hooks`.

`install` stays with `cross_stack.py`. Standing up a toolchain is a property of the runner,
not of the Definition of Done — the same line meta.yml already draws — and a report that
never installs is safe to call from a Stop hook context.

## Consequences

**The job proves layer A by using layer A.** The reporter that decides the verdict is the
artifact under test, so a layer A change that breaks the reporter fails the job that would
otherwise have shipped it. Running this checkout's copy instead would prove something about
a tree no stack will ever execute, and would leave the vendoring adapter itself ungated.

**An unchanged layer A is an honest skip.** Both stacks gate `.agents/vendor/harness/hooks`
with `.mjs`, so a sync that changes layer A makes the stack's own `gatedChange()` true by
itself, with no `--base` flag. The converse is the point: on a PR touching only `templates/`,
`scripts/` or prose, the sync is a no-op, no gate runs, and the job says so and exits 0. That
sha's own CI already proved it, and re-running both suites would measure the same tree twice.

The vacuous-green guard is retargeted rather than dropped: it fails when layer A _did_ move
and still no gate ran, which can only mean a defect in the stack's own declaration.

That guard compares two answers to "did layer A move?", and they must be asked in the same
terms or the guard fires on the difference. `MANIFEST.json` is the trap: it records the
harness sha the tree was taken at, so a sync rewrites it on every commit here whether or not
a byte of layer A changed. `cross_stack.py` excludes it; `gate_report.mjs` never saw it,
because it is outside the stacks' `gatedPaths` and is not a gated extension. Shipping without
that exclusion failed the job on every harness PR that did not touch layer A, and it was
invisible until the stacks' pins were current -- until then layer A genuinely had moved every
time.

**`incomplete` is kept apart from `fail`.** A gate that could not start does not mean layer A
broke the stack; it means the job did not find out. Reporting it as a failure would be a red
tick for the wrong reason, which teaches people to ignore the one job that says whether layer
A still works.
