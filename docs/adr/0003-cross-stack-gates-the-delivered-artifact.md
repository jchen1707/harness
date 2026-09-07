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

**An unchanged layer A is an honest skip.** Before installing, `cross_stack.py`
compares synced content with the consumer's committed tree, excluding `MANIFEST.json`:
the manifest records the source SHA and can change without shipped content changing.
An identical tree costs no install or gate run.

**Changed content requests the declared gates with `--force`.** Shared instructions and
schemas can change without touching the `.mjs` hook paths watched by a stack's Stop
hook. The original assumption that every content change satisfied those filters caused
PR #32 to fail with every gate `skipped_unchanged`. Cross-stack CI now supplies its own
content-change trigger and delegates eligibility to the reporter: disabled gates remain
disabled, opt-in gates still require explicit assertion, and probes still apply.

The vacuous-green guard remains: changed content with no executed gate fails. A skipped
gate is never counted as a passing check. A real sync/reporter regression covers an
instruction-only change, an unchanged tree, and disabled/opt-in eligibility.

**`incomplete` is kept apart from `fail`.** A gate that could not start does not mean layer A
broke the stack; it means the job did not find out. Reporting it as a failure would be a red
tick for the wrong reason, which teaches people to ignore the one job that says whether layer
A still works.
