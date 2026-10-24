# Frontend integration requests — contract 1.0.0

The initial checkout contains README.md and no application, contracts directory, machine schemas, backend, tests, router or installed frontend packages. Physical ownership follows the proposed monorepo: all application/package/build/test files live under frontend/; frontend handoff and this request live under docs/. Root files and backend remain untouched.

Coordinator action: freeze contracts/v1/CONTRACT.md, manifest.json, schemas.json, openapi.yaml, stream.schema.json and shared parity fixtures from the supplied version 1.0.0. Frontend-local DTO projections and Zod validators are provisional consumers, not edits to the contract or a claim of completed cross-language parity. The live adapter follows the supplied endpoint table; actual integration and OpenAPI parity remain blocked on those artifacts and a running backend. No contract changes are proposed.
