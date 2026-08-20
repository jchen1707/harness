# apps/web

The web client. Vite, React, TypeScript.

## Layout

```
src/main.tsx    mounts the app - nothing else belongs here
src/App.tsx     the root component
src/health.ts   a plain module: types, a guard and a fetch
src/*.test.ts   Vitest, beside the module under test
```

Logic lives in plain modules, not in components. A rule inside a component can only be
tested by rendering one, which needs a DOM, which is why this app does not have one yet.
Keep it that way for as long as the tests stay this cheap.

## Gates

`harness.config.json` here is the Definition of Done for this app: ESLint, Prettier, `tsc`
and Vitest, plus the production build. The build is a gate rather than a nicety — a
top-level `await` typechecks cleanly and still fails against the deployment target, and this
is the only gate that would notice.

## The contract

`packages/contracts/openapi.yaml` is the source of truth for what the API returns, and
`src/health.ts` currently restates one of its shapes by hand. That is the one place drift can
enter this app: generate those types from the contract and it stops being possible. A change
to the contract runs this app's gates as well as the API's, because it is named in
`gatedPaths` here.

## Types

`tsconfig.json` is strict, including `noUncheckedIndexedAccess` and
`exactOptionalPropertyTypes`. Both reject code that ordinary strict mode accepts, and both
are cheaper to satisfy while writing than to retrofit — do not relax them to make a change
compile.
