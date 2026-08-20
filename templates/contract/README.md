# The seed contract

One file, placed by `new_project.py` wherever the chosen shape keeps it:

| Shape     | Lands at                                                              |
| --------- | --------------------------------------------------------------------- |
| monorepo  | `packages/contracts/openapi.json`                                     |
| `--split` | `<api>/contracts/openapi.json` **and** `<web>/contracts/openapi.json` |

Kept once rather than once per shape. It is a **generated** document — the output of
`apps/api/scripts/emit_contract.py` against the api skeleton — and three copies of a
generated file in one repository is the drift this whole repository exists to remove. The
split shape needs it in both repos because the web repo has to build before the api has
published anything; from the first `pnpm contract:update` onwards, that copy is the api's
released artifact rather than this seed.

Regenerate it the same way the scaffold's own gate checks it:

```sh
uv run python scripts/emit_contract.py <path>   # in a scaffolded apps/api
```
