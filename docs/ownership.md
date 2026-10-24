# AgentCity ownership baseline

## Current integration scope

The user's subsequent integration request authorizes changes to both applications,
root launch/setup/check scripts and documentation. Both implementations are now
present in this checkout. The frozen `contracts/v1/**` remains unchanged. The
table below records the initial independent-backend ownership only; current
integration evidence is in [integration-handoff.md](integration-handoff.md).

## Historical baseline

The checkout initially had only a seven-byte README and `.DS_Store`, with no
application, dependency lock, schemas, tests, integrations or AGENTS.md guidance.
The backend task prepared the initial shared bootstrap because there was no
coordinator baseline or frontend checkout to consume. No separate agent or
frontend implementation was started.

| Path                                                           | Ownership                                              |
| -------------------------------------------------------------- | ------------------------------------------------------ |
| `backend/**`                                                   | Backend application, local tooling/tests/docs and lock |
| `frontend/**`                                                  | Future frontend engineer; absent and untouched         |
| `contracts/v1/**`                                              | Coordinator-owned frozen 1.0.0 integration artifact    |
| `docs/backend-handoff.md`, `docs/backend-contract-requests.md` | Backend handoff                                        |
| `docs/ownership.md`, `docs/decisions.md`                       | Initial baseline evidence/decisions                    |
| Root README, orchestration, deployment, CI                     | Preserved for coordinator integration                  |

Contract bootstrap validation corrected mechanically missing UUID/date/name/
unique-ID/numeric-bound schema constraints, distinguished request defaults from
required response members, and documented middleware headers in OpenAPI. These
were validation fixes before handing the baseline to any external consumer.
The supplied normative contract bytes and version were unchanged. The final
manifest freezes all shared files; normal backend work must not regenerate them.
