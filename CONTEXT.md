# Domain model

The words this repository uses in a particular way. `AGENTS.md` says how the repo is
organised and what the rules are; this file says what the nouns mean, so that prose, code
comments and review findings can all use the same one.

A term earns a place here when using the wrong word for it would produce a wrong change.

---

## Layers

**Layer A — stack-neutral.** The content that is identical in every consuming harness:
the shared review frames, the workflow commands, the skills, the hooks, `full-review.js`,
the config schema, and `docs/agents/`. Authored once, here, under `plugins/harness/`.
Generated into consumers and never edited there.

**Layer B — stack-specific.** What is irreducibly one stack's: its gates, its hook wiring,
its `docs/architecture.md`, its path-scoped instruction files, each frame's **checklist**.
Lives in `python-harness` / `frontend-harness`, and diverges on purpose.

**Layer C — the product.** An actual application. Scaffolded once from `templates/` and
owned by whoever scaffolded it. Nothing here runs against a layer C repo.

**Layer D — the factory.** The unattended control plane that drives an agent through a
ticket and verifies the result. It is a **consumer** of layer A, not a part of it: it reads
the gate **report** and must never re-derive any judgment the report already makes. It
lives outside this repository, which is why its name appears here without its code.

## Gates and the Definition of Done

**Gate.** One declared command that says whether the code is acceptable, named and typed in
a repo's `harness.config.json`. A gate is a `name`, a **kind**, a `run` argv, and optionally
a `when`, a `caveat`, a `requires` and an `enabled` flag. Never a command someone remembers
to type — if it is not declared, it is not a gate.

**Gate kind.** One of `lint`, `format`, `types`, `build`, `test`, `e2e`, `integration`. The
enum lives in the schema and is read from there, never restated.

**Definition of Done.** The full set of a repo's gates. A subset that passes is not a
Definition of Done that passed, which is why every partial run says what it did not run.

**Opt-in gate.** An `e2e` or `integration` gate. It needs a browser or a container, so it is
not part of the default loop — but opt-in is not optional. Only a caller can decide whether
a gate's `when` clause holds, and it holds per gate, not per run.

**Probe.** A gate's `requires` argv, run before the gate to prove the environment exists. It
is what separates "the browser was never installed" from "the test failed" — two facts a
gate's own exit code cannot tell apart, and two completely different instructions to whoever
reads them.

**Caveat.** A field on a gate naming exactly how it can pass while having checked nothing.
Printed beside a green result, never instead of one.

**The report.** `gate_report.mjs`, and the JSON document it emits. The one implementation of
which gates apply, in which directories, and what each result means. Every other caller —
the Stop hook, `/lint`, `/test`, `/verify`, the cross-stack job, the factory — goes through
it. See `docs/adr/0002-gate-report-is-the-only-gate-runner.md`.

**Vacuous green.** A pass that proved nothing: a gate that never ran, a suite with no test
covering the change, a metric that came back null, a filter that matched no files. The
failure mode this repository exists to make loud. Distinguished from an honest pass by
naming what did _not_ happen, which is why the report has `skipped_unchanged`,
`not_applicable`, `disabled` and `unavailable` rather than just pass and fail — and why its
verdict is `incomplete`, never `pass`, when a gate could not start.

## Review

**Frame.** Half a reviewer: the role, the method and the reporting rules, identical in every
stack. Layer A. Eight of them, under `plugins/harness/agents/`.

**Checklist.** The other half: what "in this repo's terms" means, at
`docs/agents/subagents/<agent-name>.md` in the stack. Layer B.

Neither is a review on its own, and both failures are silent — a frame with no checklist
reviews on general advice and reports a confident clean.

## Delivery

**Stack.** One of the two consuming harnesses, `python-harness` or `frontend-harness`.
Mounted here as submodules for reading. Work is never committed to a stack through this
repo.

**Adapter.** One of the two ways layer A reaches a consumer: the **plugin** (Claude Code,
resolved via `${CLAUDE_PLUGIN_ROOT}`) or the **vendored tree** (committed files under
`.agents/vendor/harness/`). Both lay out `commands/`, `hooks/` and `skills/` under one root,
which is why a command file can address a hook by a path relative to itself.

**Pin.** The sha a consumer's vendored copy was taken at. Vendoring's cost is staleness and
the pin is what makes staleness measurable: `vendor_sync.py check` reports "N commits
behind" rather than letting the copy drift quietly.

**Drift.** Two copies of one fact going out of step. The thing this repository exists to
prevent, and the lens every architecture decision here is judged through. Drift is dangerous
because it is silent: the stale copy keeps working, keeps passing, and keeps answering an
out-of-date question.
