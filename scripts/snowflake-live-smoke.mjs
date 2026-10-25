import { backend, backendEnv, python, run } from "./runtime.mjs";
if (process.argv.length !== 3 || process.argv[2] !== "--live") {
  throw new Error(
    "Explicit paid opt-in required: node scripts/snowflake-live-smoke.mjs --live",
  );
}
try {
  run(python, ["-m", "scripts.snowflake_smoke", "--live"], {
    cwd: backend,
    env: backendEnv(),
  });
} catch {
  process.exitCode = 1;
}
