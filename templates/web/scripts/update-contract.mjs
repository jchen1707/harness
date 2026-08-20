/**
 * Fetch the api's published contract at the version this repository pins, then regenerate.
 *
 * **This is the seam that makes two repositories survivable.** Without it the client holds a
 * hand-maintained description of a shape the api owns, and nothing detects the drift. With
 * it the drift becomes a version bump that either type-checks or does not.
 *
 * Deliberately not a gate: it reaches the network, and a gate that cannot run offline is a
 * gate that fails for reasons unrelated to the code. The fetched document is committed, and
 * `prepare` regenerates types from that committed copy on every install — so CI needs no
 * network to check that the client and the contract agree.
 */
import { writeFileSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';

const PIN = 'contract.json';
const OUTPUT = 'contracts/openapi.json';

const pin = JSON.parse(await readFile(PIN, 'utf8'));
if (!pin.repo || pin.repo.startsWith('OWNER/')) {
  console.error(
    `${PIN} still names OWNER/... — set \`repo\` to the api repository, as owner/name.`,
  );
  process.exit(1);
}

const url = `https://github.com/${pin.repo}/releases/download/${pin.version}/openapi.json`;
console.log(`fetching ${url}`);
const response = await fetch(url);
if (!response.ok) {
  console.error(
    `${response.status} ${response.statusText}. Either that version has no contract ` +
      `attached, or the repository is private — a private api needs ` +
      `\`gh release download ${pin.version} -R ${pin.repo} -p openapi.json\` instead.`,
  );
  process.exit(1);
}

writeFileSync(OUTPUT, await response.text());
console.log(`wrote ${OUTPUT} at ${pin.version}`);

const result = spawnSync('pnpm', ['contract:types'], {
  stdio: 'inherit',
  shell: process.platform === 'win32',
});
process.exit(result.status ?? 1);
