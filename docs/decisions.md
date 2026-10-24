# Baseline decisions

| Decision | Evidence / reason |
|---|---|
| Implement a new backend in `backend/` | Initial `rg --files` and git status showed no application or useful prior code |
| Use exact contract 1.0.0 | All three supplied embedded contract blocks had identical SHA-256; verbatim standalone file is preserved |
| Local durable repository, one writer | No existing database; explicit contract baseline, atomic manifest tests and second-writer denial |
| Rules work without credentials | Required real integration path; all recorded simulation traces identify rules decisions |
| Explicit request adapters | Request setup defaults normalize into canonical models whose response fields are required; JSON numeric 10.0 equals integer 10 without accepting strings/bools |
| Bounded scenario compilation | Only advertised EffectSpec mechanics execute; preview warnings/unsupported notices are retained |
| Derived metric overrides preserve rules | Safety cannot outrun a hazard; resource changes use conserved nearby transfers rather than inventing inventory |
| Unknown provider usage is unavailable | Usage has no nullable counters; return explicit 503 for an incomplete total, retain known metadata internally, charge conservative internal budget |
| Optional integrations stay unavailable | No operational PostgreSQL/Snowflake/ElevenLabs adapter or supplied accounts; capabilities are honest |
| Preserve root/frontend ownership | No root deployment/CI/frontend changes; provide a backend-local deployment recipe |

The original planning PDF and its image-only pages were not supplied to this
task. Implementation follows the provided prompt and shared contract, without
claims about unseen diagram details.
