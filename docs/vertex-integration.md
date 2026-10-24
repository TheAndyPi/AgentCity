# Vertex AI integration verification

Verified locally on October 24, 2026 using project `agentcityx`, service account
`agentcity-backend@agentcityx.iam.gserviceaccount.com`, model
`gemini-3.5-flash-lite`, and location `global`.
The model ID, structured output support, and global availability were checked
against [Google's model documentation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite).

## Results

- Authentication: the supplied service-account JSON successfully exchanged for
  Google Cloud credentials, without a personal browser login.
- Inference: a direct Vertex `generateContent` request returned HTTP 200.
  AgentCity's gateway also returned a schema-validated structured decision.
- Application integration: `npm run test:gemini -- --application` launched a real
  isolated backend, created and played a city over HTTP, and retrieved an accepted
  Gemini `talk` decision at tick 3 through the public decision API. The disposable
  city was paused and its temporary storage removed.
- Local verification: `npm test` passed 81 frontend and 131 backend tests, frozen
  contract checks, TypeScript, and Ruff. After adding one final routing-precedence
  regression, the provider suite passed all 14 tests. The credential scan found
  no supplied private-key material in Git-eligible repository files.

The first structured request was rejected with HTTP 400 because its content
omitted `role`. Requests now explicitly set `role: user`; the provider regression
test asserts it.

## Credentials and routing

The local `.env` contains an absolute `GOOGLE_APPLICATION_CREDENTIALS` path to a
JSON file outside this repository. The directory is restricted to its owner
(`700`) and the file is owner-readable/writable only (`600`). Neither the JSON
nor its private key is included in this report, frontend, or tracked source.

Vertex uses Google Cloud bearer authentication and project-scoped endpoints.
It does not send the AI Studio key or fall back to the Developer API.
Google-auth refreshes credentials off the simulation event loop. Existing
timeouts, bounded retries, concurrency/rate/token limits, circuit breaking,
stale-result checks, rules fallback, and Game Master validation remain in place.
Error diagnostics retain only categories and HTTP status codes.

## Scope

Billing availability and trial credit were supplied by the user; this application
test did not independently verify billing credits or their consumption. No billing,
IAM, API enablement, or organization policy was modified. Optional database,
analytics, and narration adapters remain separate work. Gemini remains limited
to the existing persona/decision pipeline.

Repeat the live checks from the repository root:

```sh
npm run test:gemini
npm run test:gemini -- --application
```
