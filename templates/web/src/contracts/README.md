# contracts

`types.gen.ts` is generated from the api's OpenAPI document at install time — `prepare` runs
`pnpm contract:types`, so it exists after `pnpm install` and can never be older than the
schema it came from.

**It is not committed, and it is not written by hand.** A hand-written mirror of a response
shape type-checks perfectly against itself, which is precisely why it is worthless as a
check: it agrees with whatever you last believed. Generated from the api's own document, a
shape change the client has not followed is a compile error.

The api emits that document from its handlers and gates it, so the chain has no hand-written
link in it: handler → `openapi.json` → `types.gen.ts` → `tsc`.
