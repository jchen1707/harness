#!/usr/bin/env node
/**
 * The machine-readable gate report: every gate the config declares, with a verdict.
 *
 * `verify.mjs` is a Stop *hook*: it runs only `STOP_KINDS`, it returns 0 when a gate could
 * not start, it never prints a `caveat`, and its output is prose on stderr. The `/verify`
 * skill prints caveats and covers `e2e`/`integration`, but its output is a chat message.
 * Neither is a machine record. This file is: one JSON document on stdout that says exactly
 * which gates ran, which passed, which were unavailable, which were not applicable, and
 * every caveat — the third of the three independent verification signals in §15.1.
 *
 * It reuses layer A rather than re-authoring it. `dispatch`, `gatedChange`, `isGated` and
 * `STOP_KINDS` come from `./verify.mjs`; `loadConfig`, `runArgv`, `repoRelative` and `tail`
 * come from `./lib.mjs`. No classification logic is copied, so the report and the Stop hook
 * cannot drift apart on what "this app was touched" or "this gate is opt-in" means. The
 * factory (layer D) reads this document; it must never re-derive which gates apply, because
 * that would re-author `dispatch()` and `STOP_KINDS` in Python where they would drift
 * silently — the single failure this repository exists to prevent.
 *
 * ```
 * node gate_report.mjs [--all] [--json] [--cwd <dir>]
 * ```
 *
 * `--all` runs the `e2e`/`integration` gates too. Without it they are `not_applicable`,
 * because opt-in is not optional: the caller asserts a gate's `when` clause by passing this
 * flag, and the factory makes that decision from the agent's structured answer plus a
 * deterministic path check against `harness.config.json`'s own `gatedPaths` — never by
 * pattern-matching the diff here.
 *
 * `--json` emits the document below. Without it, a compact human-readable summary goes to
 * stdout and the same exit code is returned, so an interactive run is legible without a
 * pipe. The factory always passes `--json`.
 *
 * ## Classification
 *
 * | status | Meaning |
 * | --- | --- |
 * | `pass` | exit 0, and the gate actually started |
 * | `fail` | non-zero exit |
 * | `unavailable` | the process could not be spawned (`result.error`) — the case `verify.mjs` must swallow and a report must not |
 * | `not_applicable` | `kind` is `e2e`/`integration`, no `--all`, and the `when` clause was not asserted by the caller |
 * | `skipped_unchanged` | the app's `gatedChange()` was false — a monorepo app the turn never touched |
 *
 * ## The verdict
 *
 * `verdict` is `pass`, `fail` or `incomplete`. It is **`incomplete` — never `pass`** when any
 * gate is `unavailable`, or when any app named in a root config had no config of its own.
 * That single rule is the whole answer to "a green exit code does not prove every relevant
 * gate ran": a gate that could not start is reported, never rounded to green.
 *
 * Exit codes are distinct so a caller that reads only the exit code still cannot mistake
 * incomplete for pass: `0` pass, `1` fail, `3` incomplete. A real `fail` outranks
 * `incomplete`, because a failing gate is the more actionable signal; the exit code is the
 * verdict's, with that precedence.
 */

import { performance } from 'node:perf_hooks';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

import { loadConfig, repoRelative, runArgv, tail } from './lib.mjs';
import { dispatch, gatedChange, STOP_KINDS } from './verify.mjs';

const MAX_LINES = 40;
const GATE_TIMEOUT = 540_000;

/** Schema version of the emitted document. Bumped only on a breaking shape change. */
export const REPORT_SCHEMA_VERSION = 1;

/** Exit codes, distinct so an exit-code-only caller cannot mistake incomplete for pass. */
export const EXIT = { pass: 0, fail: 1, incomplete: 3 };

/**
 * The run result a gate produced, plus how long it took.
 *
 * `status` is `null` when the process could not be spawned — the `unavailable` case. The
 * `durationMs` is measured by the caller that actually runs the gate, so the pure report
 * builder below never touches a clock.
 *
 * @typedef {Object} GateRun
 * @property {number|null} status
 * @property {string} stdout
 * @property {string} stderr
 * @property {Error|null} error
 * @property {number|null} durationMs
 */

/**
 * The outcome of one gate, in the shape the JSON document emits.
 *
 * @typedef {Object} GateEntry
 * @property {string} name
 * @property {string} kind
 * @property {string} status
 * @property {number|null} exit
 * @property {number|null} durationMs
 * @property {string|null} caveat
 * @property {string|null} when
 * @property {string} outputTail
 */

/**
 * Classify a gate that ran, from its run result.
 *
 * The one judgment this encodes: a process that could not start is `unavailable`, not `fail`
 * and not `pass`. `verify.mjs` swallows exactly this case (it returns 0 so a tooling problem
 * does not wedge the turn); a report must not, because "the gate could not run" is the fact
 * the factory most needs to hear.
 *
 * @param {GateRun} run
 * @returns {'pass'|'fail'|'unavailable'}
 */
export function classifyRun(run) {
  if (run.error) return 'unavailable';
  return run.status === 0 ? 'pass' : 'fail';
}

/**
 * One gate's entry, given its status and the run that produced it (or `null` when it did not
 * run). Fields are uniform across every status so a reader never has to special-case the
 * shape: `exit`, `durationMs` and `outputTail` are `null`/`''` for the statuses that did not
 * execute anything, and `caveat`/`when` are always present (they name how a green result
 * proved nothing, which matters beside a `pass` too).
 *
 * @param {Object} gate
 * @param {string} status
 * @param {GateRun|null} run
 * @returns {GateEntry}
 */
function gateEntry(gate, status, run) {
  const entry = {
    name: gate.name,
    kind: gate.kind,
    status,
    exit: null,
    durationMs: null,
    caveat: gate.caveat ?? null,
    when: gate.when ?? null,
    outputTail: '',
  };
  if (run && (status === 'pass' || status === 'fail' || status === 'unavailable')) {
    entry.exit = run.error ? null : run.status;
    entry.durationMs = run.durationMs ?? null;
    if (status !== 'pass') {
      const out = (run.stdout ?? '') + (run.stderr ?? '');
      entry.outputTail = tail(out, MAX_LINES) || (run.error?.message ?? '') || '(no output)';
    }
  }
  return entry;
}

/**
 * The verdict for a set of gate entries and the apps that had no config of their own.
 *
 * `fail` outranks `incomplete`: a failing gate is more actionable than a missing one, and the
 * exit code follows the verdict. `incomplete` — never `pass` — when anything was
 * `unavailable` or an app was missing, so a green exit code can never stand in for "every
 * relevant gate ran." Everything else is `pass`, including the `not_applicable` and
 * `skipped_unchanged` rows: those are documented dispatch decisions, not checks that failed
 * to run.
 *
 * @param {GateEntry[]} gates
 * @param {string[]} missing
 * @returns {'pass'|'fail'|'incomplete'}
 */
export function computeVerdict(gates, missing) {
  if (gates.some((gate) => gate.status === 'fail')) return 'fail';
  if (gates.some((gate) => gate.status === 'unavailable') || missing.length > 0)
    return 'incomplete';
  return 'pass';
}

/** The exit code for a verdict. */
export function exitCode(verdict) {
  return EXIT[verdict] ?? EXIT.incomplete;
}

/**
 * Build the full report from dispatched targets, without touching a subprocess.
 *
 * The two side effects a real run needs — "was this app touched?" and "run this gate" — are
 * injected, so the same logic runs in tests against fakes with no `git` and no toolchain.
 * That mirrors `gatedChangeWith` in the hook suite, and for the same reason: a unit test
 * must not shell out.
 *
 * `isChanged(target)` answers the same question `verify.mjs` asks before it runs an app's
 * gates: did the turn touch a path this app gates? When it did not, every gate for that app
 * is `skipped_unchanged` — a monorepo app the turn never reached, rather than a green tick
 * for a suite that never ran.
 *
 * `runGate(gate, target)` returns a {@link GateRun}. It is called only for gates that
 * actually run, so a fake never has to answer for a `not_applicable` or `skipped_unchanged`
 * gate.
 *
 * @param {Object} args
 * @param {Object} args.root - The root config, as `loadConfig` returns it.
 * @param {Object[]} args.targets - The dispatched targets, as `dispatch` returns them.
 * @param {string[]} args.missing - Apps named in the root config with no config of their own.
 * @param {boolean} [args.all=false] - Whether the caller asserted the opt-in `when` clauses.
 * @param {(target: Object) => boolean} args.isChanged
 * @param {(gate: Object, target: Object) => GateRun} args.runGate
 * @returns {Object} the JSON document
 */
export function buildReport({ root, targets, missing, all = false, isChanged, runGate }) {
  const gates = [];
  for (const target of targets) {
    const prefix = repoRelative(target.root, root.root);
    const dir = prefix || '.';
    const changed = isChanged(target);
    // The same filter the Stop hook uses: a gate without a `run` argv is malformed config,
    // not a gate to attempt. Reporting it would mean executing `undefined`.
    const declared = target.gates.filter((gate) => gate && Array.isArray(gate.run));
    for (const gate of declared) {
      if (!changed) {
        gates.push(gateEntry(gate, 'skipped_unchanged', null));
        continue;
      }
      // The opt-in kinds are exactly the ones the Stop hook does not run — the complement
      // of `STOP_KINDS` — so this reuses layer A's own line rather than re-authoring the
      // e2e/integration list here. A new opt-in kind added to the enum is `not_applicable`
      // without `--all` automatically, the same way it stops being a Stop gate.
      if (!STOP_KINDS.has(gate.kind) && !all) {
        gates.push(gateEntry(gate, 'not_applicable', null));
        continue;
      }
      // Run once: `runGate` shells out in production, so calling it twice would run every
      // gate twice. The result is classified and recorded from the same run.
      const run = runGate(gate, target);
      gates.push(gateEntry(gate, classifyRun(run), run));
    }
  }

  const verdict = computeVerdict(gates, missing);
  return {
    schemaVersion: REPORT_SCHEMA_VERSION,
    root: root.root,
    targets: targets.map((target) => ({
      name: target.name,
      dir: repoRelative(target.root, root.root) || '.',
    })),
    missingApps: missing,
    gates,
    verdict,
  };
}

/** Run a gate's argv and time it. Returns a {@link GateRun} with `durationMs` set. */
function timedRun(argv, options) {
  const start = performance.now();
  const result = runArgv(argv, options);
  return { ...result, durationMs: Math.round(performance.now() - start) };
}

/**
 * Parse the CLI flags. Deliberately tiny: `--all`, `--json`, `--cwd <dir>` (or `--cwd=<dir>`).
 * No abbreviations, no `--no-*` — a report's caller is a machine or a person who read the
 * help line above, and a forgiving parser is a parser that silently does the wrong thing.
 */
function parseArgs(argv) {
  const args = { all: false, json: false, cwd: '' };
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i];
    if (flag === '--all') args.all = true;
    else if (flag === '--json') args.json = true;
    else if (flag === '--cwd') args.cwd = argv[++i] ?? '';
    else if (flag.startsWith('--cwd=')) args.cwd = flag.slice('--cwd='.length);
  }
  return args;
}

/** One line per gate for a human reader, then the verdict. ASCII only, like the hook's stderr. */
function humanReport(report) {
  const lines = [];
  for (const gate of report.gates) {
    const where = report.targets.length > 1 ? ` (${gate.name})` : '';
    lines.push(`${gate.status}\t${gate.name}${where}`);
    if (gate.caveat && (gate.status === 'pass' || gate.status === 'not_applicable')) {
      lines.push(`\tcaveat: ${gate.caveat}`);
    }
  }
  if (report.missingApps.length > 0) {
    lines.push(`incomplete\tapps with no config: ${report.missingApps.join(', ')}`);
  }
  lines.push(`verdict: ${report.verdict}`);
  return lines.join('\n');
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const cwd = args.cwd || process.cwd();
  const root = loadConfig(cwd);
  const { targets, missing } = dispatch(root);

  const report = buildReport({
    root,
    targets,
    missing,
    all: args.all,
    isChanged: (target) =>
      gatedChange(target.root, target.hooks, repoRelative(target.root, root.root)),
    runGate: (gate, target) => timedRun(gate.run, { cwd: target.root, timeout: GATE_TIMEOUT }),
  });

  if (args.json) process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  else process.stdout.write(`${humanReport(report)}\n`);
  return exitCode(report.verdict);
}

const invoked = process.argv[1] ? resolve(process.argv[1]) : '';
if (invoked === resolve(fileURLToPath(import.meta.url))) {
  process.exit(await main());
}
