#!/usr/bin/env node
/**
 * Stop hook: refuse to end the turn while the Definition of Done is failing.
 *
 * Smart by design — the gates only run when the turn touched something that can actually
 * make them fail. That is the line: **code the gates check, plus the config that defines
 * the gates**. Prose, plans and docs still end freely, so writing work never burns toward
 * the 8-consecutive-block override Claude Code applies to Stop hooks.
 *
 * Which paths qualify is the consuming repo's declaration, in `harness.config.json` under
 * `hooks.gatedPaths`, `hooks.gatedFiles` and `hooks.gatedExtensions`. Both stacks arrived at
 * the same three groups by different routes, and the doctrine is worth restating because a
 * config is easy to narrow by accident:
 *
 * - The application and its tests.
 * - **The hooks themselves.** They are code the gates check, so a broken edit here fails
 *   the same gates as application code. Leaving them out meant the enforcement layer was
 *   the one thing the walk-away gate could not catch. Since phase 5 they are vendored
 *   rather than repo-owned, so what a stack gates is its own wiring — its settings file and
 *   its Codex adapter — plus the vendored tree, which its freshness check also covers.
 * - **The tool config that defines the gates.** A change to it can break every gate at once
 *   while touching no application code.
 *
 * The tradeoff this balances: widening the filter costs some override budget on config
 * work, but the excluded set that motivated the original narrow filter — Markdown, plans,
 * docs — is still excluded, and those are what sessions actually churn on.
 *
 * Convergence matters: every gate here is one an agent can actually fix. A check that can
 * never pass just wastes 8 turns of tokens before being overridden anyway.
 *
 * **Caveats are not printed here.** A gate's `caveat` names how it passes without having
 * checked anything, and the natural place to say so is beside a green result — but a Stop
 * hook that exits 0 has its stderr discarded, so printing them here reaches nobody. The
 * `/verify` skill prints them, because a human asked it a question and will read the
 * answer. What this hook adds instead is the other half: when it blocks, it names the
 * declared gates it did **not** run, so a passing subset is never mistaken for the whole
 * Definition of Done.
 *
 * Escape hatch: set `HARNESS_SKIP_VERIFY=1` to disable for a session. The legacy
 * `CLAUDE_SKIP_VERIFY` name remains supported — the gate is not Claude's, and naming it
 * after one harness is how the same escape hatch ended up with two names in two repos.
 */

import { resolve } from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import { loadConfig, readPayload, run, runArgv, tail } from './lib.mjs';

const MAX_LINES = 40;
const GATE_TIMEOUT = 540_000;

/**
 * Gate kinds a Stop hook runs. `build` is in because it is the only gate that sees the
 * deployment target — a top-level `await` passes a typecheck and still fails a build
 * against es2020. `e2e` and `integration` are out: they need a browser or a container, and
 * a gate that cannot start on a given machine converts a walk-away gate into a wedged turn.
 */
export const STOP_KINDS = new Set(['lint', 'format', 'types', 'test', 'build']);

/**
 * Extract the path from one `git status --porcelain` line.
 *
 * Format is two status chars, a space, then the path. Renames and copies read
 * `old -> new`; the destination is the one that exists on disk. Paths containing special
 * characters are quoted.
 */
export function porcelainPath(line) {
  const entry = line.slice(3).trim();
  const arrow = entry.lastIndexOf(' -> ');
  const path = arrow === -1 ? entry : entry.slice(arrow + 4);
  return path.trim().replace(/^"|"$/g, '');
}

/** True if `path` is something the gates would read. */
export function isGated(path, hooks) {
  if (hooks.gatedFiles.includes(path)) return true;
  return hooks.gatedExtensions.some((extension) => path.endsWith(extension));
}

/**
 * True if the turn touched gated source or the tool config that gates it.
 *
 * The pathspec names every gated location explicitly rather than asking git about the whole
 * tree: a repo-wide `git status` in a large checkout is slow enough to notice on every
 * turn, and narrowing it here is what makes the filter affordable.
 */
export function gatedChange(cwd, hooks) {
  const pathspec = [...hooks.gatedPaths, ...hooks.gatedFiles];
  if (pathspec.length === 0) return false; // Nothing declared -> nothing to gate.

  const result = run('git', ['status', '--porcelain', '--', ...pathspec], {
    cwd,
    timeout: 30_000,
  });
  if (result.status !== 0) return false; // Can't tell -> don't block.
  return result.stdout
    .split(/\r?\n/)
    .filter(Boolean)
    .map(porcelainPath)
    .some((path) => isGated(path, hooks));
}

/** One line per declared gate this hook does not run, naming when it stops being optional. */
export function skippedNote(gates) {
  const skipped = gates.filter((gate) => !STOP_KINDS.has(gate?.kind));
  if (skipped.length === 0) return '';
  const lines = skipped.map(
    (gate) => `  - ${gate.name} (${gate.kind})${gate.when ? `: required when ${gate.when}` : ''}`,
  );
  return `\n\nGates this hook does not run, which are still part of the Definition of Done:\n${lines.join('\n')}`;
}

async function main() {
  if (process.env.HARNESS_SKIP_VERIFY === '1' || process.env.CLAUDE_SKIP_VERIFY === '1') return 0;

  const payload = await readPayload();
  if (!payload) return 0;

  const cwd = payload.cwd ?? '';
  const config = loadConfig(cwd);
  if (!config.found) return 0; // Nothing declares this repo's Definition of Done.

  if (!gatedChange(cwd, config.hooks)) return 0;

  const gates = config.gates.filter((gate) => gate && Array.isArray(gate.run));
  for (const gate of gates) {
    if (!STOP_KINDS.has(gate.kind)) continue;

    const result = runArgv(gate.run, { cwd: config.root, timeout: GATE_TIMEOUT });
    if (result.error) {
      process.stderr.write(`Could not run \`${gate.name}\`: ${result.error.message}\n`);
      return 0; // Tooling problem, not a code problem -> don't block.
    }
    if (result.status !== 0) {
      const out = tail(result.stdout + result.stderr, MAX_LINES) || '(no output)';
      // ASCII only - see protect_paths.mjs.
      process.stderr.write(
        `Definition of Done is failing at \`${gate.name}\`. Fix this before finishing. ` +
          `Do not summarise the failure as if it were done.\n\n${out}${skippedNote(gates)}\n`,
      );
      return 2;
    }
  }
  return 0;
}

const invoked = process.argv[1] ? resolve(process.argv[1]) : '';
if (invoked === resolve(fileURLToPath(import.meta.url))) {
  process.exit(await main());
}
