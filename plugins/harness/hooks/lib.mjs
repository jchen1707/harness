/**
 * Shared plumbing for the hooks in this directory.
 *
 * Dependency-free on purpose, and that is a harder constraint here than it was in either
 * stack. These hooks run in a Python repository as well as a Node one, and in a vendored
 * tree that no package manager has ever visited. There is no `node_modules` to reach for
 * and no install step to add one, so the only requirement is Node 22 itself.
 *
 * Everything a hook needs to know about the repository it is running in comes from that
 * repository's `harness.config.json`. Layer A names no toolchain, no directory and no
 * team key; see `schema/harness.config.schema.json` for the contract.
 */

import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join, parse } from 'node:path';
import process from 'node:process';

/**
 * Windows has no executable `pnpm` or `uv` on PATH — only `pnpm.cmd`, which `spawnSync`
 * finds only through a shell. POSIX needs no shell, so it does not get one.
 */
const USE_SHELL = process.platform === 'win32';

/**
 * Characters that change meaning inside `cmd.exe`. Any argument built from a tool payload
 * is checked against this before it reaches a shelled command.
 */
const SHELL_META = /[&|<>^"%!]/;

/** True when `value` is safe to place in a shelled command line. */
export function shellSafe(value) {
  return !SHELL_META.test(value);
}

/**
 * Run a command and return `{ status, stdout, stderr, error }`.
 *
 * `encoding` is explicit rather than the default Buffer: decoding a Buffer with the locale
 * codec (cp1252 on Windows) turns every em-dash and curly quote in a ruff, mypy, ESLint or
 * tsc diagnostic into mojibake — corrupting the exact message the hook exists to echo back.
 *
 * Never throws. A tool that will not start is a tooling problem, and a hook must not
 * convert one into a blocked turn.
 */
export function run(command, args, { cwd, timeout = 120_000, env } = {}) {
  const quoted = USE_SHELL ? args.map((a) => (a.includes(' ') ? `"${a}"` : a)) : args;
  const result = spawnSync(command, quoted, {
    cwd: cwd || undefined,
    encoding: 'utf8',
    timeout,
    shell: USE_SHELL,
    windowsHide: true,
    env,
  });
  return {
    status: result.error ? null : result.status,
    stdout: result.stdout ?? '',
    stderr: result.stderr ?? '',
    error: result.error ?? null,
  };
}

/** Run an argv array — the form every command in `harness.config.json` takes. */
export function runArgv(argv, options) {
  const [command, ...args] = argv;
  return run(command, args, options);
}

/** stdout of a command, or `''` on any non-zero exit or failure to start. */
export function output(command, args, options) {
  const result = run(command, args, options);
  return result.status === 0 ? result.stdout.trim() : '';
}

/** Read the hook payload from stdin. Returns `null` when it is absent or malformed. */
export async function readPayload() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    return null; // Never block because the hook itself could not parse.
  }
}

/** Repo-relative, forward-slashed form of a path the harness reported. */
export function relativePath(raw, projectDir) {
  let path = raw.replaceAll('\\', '/');
  const root = (projectDir || '').replaceAll('\\', '/').replace(/\/+$/, '');
  if (root && path.toLowerCase().startsWith(`${root.toLowerCase()}/`)) {
    path = path.slice(root.length + 1);
  }
  // Collapse `./` and `a/../b` without touching a leading dot: stripping "./" with a trim
  // would turn ".env" into "env" and defeat every dotfile rule.
  const parts = [];
  for (const part of path.split('/')) {
    if (part === '.' || part === '') continue;
    if (part === '..' && parts.length > 0 && parts.at(-1) !== '..') parts.pop();
    else parts.push(part);
  }
  return parts.join('/');
}

/** Return every file path named by a file tool or a unified-patch call. */
export function toolPaths(payload) {
  const direct = payload?.tool_input?.file_path;
  if (typeof direct === 'string' && direct) return [direct];

  // Codex sends the patch body in `tool_input.command`. Claude sends a shell command under
  // the same key, so the patch markers rather than the tool name decide: a Bash call that
  // happens to be inspected here simply yields no paths.
  const command = payload?.tool_input?.command ?? payload?.tool_input?.patch;
  if (typeof command !== 'string') return [];

  return [...command.matchAll(/^\*\*\* (?:Add|Update|Delete) File: (.+)$/gm)].map((match) =>
    match[1].trim(),
  );
}

/** The last `count` lines of `text`. */
export function tail(text, count) {
  return text.trim().split(/\r?\n/).slice(-count).join('\n');
}

/**
 * Compile one glob to a regular expression.
 *
 * `**` crosses directory separators, `*` does not — the distinction is what lets `dist/**`
 * cover a whole tree while `.env.*` stays confined to one path segment.
 */
export function globToRegExp(pattern) {
  let source = '';
  for (let i = 0; i < pattern.length; i += 1) {
    const char = pattern[i];
    if (char === '*' && pattern[i + 1] === '*') {
      if (pattern[i + 2] === '/') {
        source += '(?:.*/)?'; // A `**/` prefix must also match zero directories.
        i += 2;
      } else {
        source += '.*';
        i += 1;
      }
    } else if (char === '*') source += '[^/]*';
    else if (char === '?') source += '[^/]';
    else source += char.replace(/[.+^${}()|[\]\\]/g, '\\$&');
  }
  return new RegExp(`^${source}$`);
}

export const CONFIG_NAME = 'harness.config.json';

/**
 * Walk up from `start` for the nearest `harness.config.json`.
 *
 * Upward rather than at a fixed path, for the shape phase 6 scaffolds: a monorepo declares
 * one config per app, and a hook firing on `apps/web/src/x.ts` must find `apps/web`'s gates
 * rather than the root's. A repo with one config at its root is the same search, terminating
 * on the first step.
 */
export function findConfig(start) {
  let dir = start || process.cwd();
  const { root } = parse(dir);
  for (;;) {
    const candidate = join(dir, CONFIG_NAME);
    try {
      readFileSync(candidate);
      return candidate;
    } catch {
      // Not here. Keep walking.
    }
    if (dir === root) return '';
    const parent = dirname(dir);
    if (parent === dir) return '';
    dir = parent;
  }
}

/** Every key a hook reads, with the value it takes when the config does not say. */
const HOOK_DEFAULTS = {
  gatedPaths: [],
  gatedFiles: [],
  gatedExtensions: [],
  protected: [],
  allowed: [],
  secretVars: [],
  formatters: [],
};

/**
 * The consuming repository's config, normalised.
 *
 * Returns `{ found, root, name, gates, hooks }`. **Never throws and never reports a
 * problem**: a hook that dies on a malformed config is a hook that stops enforcing, and
 * one that writes to stderr on every tool call is one that gets disabled. `found` is false
 * when there is no config or it does not parse, and each caller decides what that means —
 * `verify` has no gates to run, while `protect_paths` still applies its built-in floor.
 */
export function loadConfig(cwd) {
  const path = findConfig(cwd);
  const empty = {
    found: false,
    root: cwd || process.cwd(),
    name: '',
    gates: [],
    hooks: { ...HOOK_DEFAULTS },
  };
  if (!path) return empty;

  let parsed;
  try {
    parsed = JSON.parse(readFileSync(path, 'utf8'));
  } catch {
    return empty;
  }
  if (!parsed || typeof parsed !== 'object') return empty;

  const declared = parsed.hooks && typeof parsed.hooks === 'object' ? parsed.hooks : {};
  const hooks = { ...HOOK_DEFAULTS };
  for (const key of Object.keys(HOOK_DEFAULTS)) {
    if (Array.isArray(declared[key])) hooks[key] = declared[key];
  }

  return {
    found: true,
    root: dirname(path),
    name: typeof parsed.name === 'string' ? parsed.name : '',
    gates: Array.isArray(parsed.gates) ? parsed.gates : [],
    hooks,
  };
}
