import js from '@eslint/js';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist', 'coverage', 'src/contracts/types.gen.ts'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    // The build scripts run in Node, not the browser. Declared here rather than pulled in
    // with the `globals` package: four names are cheaper to write than a dependency, and
    // naming them is a better record of what these scripts are allowed to reach for.
    files: ['scripts/**/*.mjs'],
    languageOptions: {
      globals: {
        console: 'readonly',
        fetch: 'readonly',
        process: 'readonly',
        URL: 'readonly',
      },
    },
  },
);
