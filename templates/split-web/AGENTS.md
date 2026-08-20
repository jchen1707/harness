# **PROJECT**-web

The web client. Vite, React, TypeScript. A repository of its own, consuming the contract
published by `__PROJECT__-api`.

## Layout

```
src/main.tsx        mounts the app - nothing else belongs here
src/App.tsx         the root component
src/health.ts       a plain module: types, a guard and a fetch
src/*.test.ts       Vitest, beside the module under test
contracts/          the api's document, at the version contract.json pins
scripts/            the contract fetcher and the type generator
```

Logic lives in plain modules, not in components. A rule inside a component can only be tested
by rendering one, which needs a DOM, which is why this app does not have one yet.

## The contract, and the only safe way to hold one

`contract.json` pins a version of the api's published document. `pnpm contract:update`
fetches that version into `contracts/openapi.json` and regenerates
`src/contracts/types.gen.ts`; `pnpm install` regenerates the types from the committed
document, so they can never be older than it.

**Never hand-write a type the contract already describes.** A hand-written mirror
type-checks against itself and agrees with whatever the author last believed — which is the
exact failure the split shape is most exposed to, because nothing else in this repository
can see the api. Generated from the document, a shape change you have not followed is a
compile error.

Taking a new api version is a deliberate act, in its own change:

1. bump `version` in `contract.json`;
2. `pnpm contract:update`;
3. follow the type errors, and commit the document with the code that answers it.

## Gates

`harness.config.json` is the Definition of Done: ESLint, Prettier, `tsc`, Vitest and the
production build. The build is a gate rather than a nicety — a top-level `await` typechecks
cleanly and still fails against the deployment target.

`pnpm contract:update` is **not** a gate. It reaches the network, and a gate that cannot run
offline fails for reasons unrelated to the code. The committed document is what CI checks
against.

## Types

`tsconfig.json` is strict, including `noUncheckedIndexedAccess` and
`exactOptionalPropertyTypes`. Both reject code that ordinary strict mode accepts, and both are
cheaper to satisfy while writing than to retrofit — do not relax them to make a change
compile.
