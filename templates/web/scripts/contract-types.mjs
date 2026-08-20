/**
 * Generate the client's types from whichever contract this repository keeps.
 *
 * Two shapes, one script. In a monorepo the api and the schema are in the same tree, so the
 * contract is read straight from `packages/contracts/`. In a split repository it is a
 * released artifact this repo pinned and committed under `contracts/`. Nothing else about
 * the client differs, and a second `package.json` script per shape would be a second thing
 * to keep in step.
 *
 * Run by `prepare`, so the generated file exists after `pnpm install` and can never be
 * older than the document it came from.
 */
import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

const CANDIDATES = ['../../packages/contracts/openapi.json', 'contracts/openapi.json'];
const OUTPUT = 'src/contracts/types.gen.ts';

const contract = CANDIDATES.find((path) => existsSync(path));
if (!contract) {
  console.error(
    `No contract found. Looked for:\n${CANDIDATES.map((p) => `  ${p}`).join('\n')}\n` +
      'In a split repository, `pnpm contract:update` fetches the pinned release.',
  );
  process.exit(1);
}

const result = spawnSync('openapi-typescript', [contract, '-o', OUTPUT], {
  stdio: 'inherit',
  shell: process.platform === 'win32',
});
process.exit(result.status ?? 1);
