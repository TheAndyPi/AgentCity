import { backend, backendEnv, python, run } from "./runtime.mjs";
if (process.argv[2] !== "--live" || process.argv.slice(3).some(arg => arg !== "--existing-schema")) {
  throw new Error(
    "Explicit paid opt-in required: node scripts/snowflake-live-smoke.mjs --live",
  );
}
try {
  run(python, ["-m", "scripts.snowflake_smoke", ...process.argv.slice(2)], {
    cwd: backend,
    env: backendEnv(),
  });
} catch {
  process.exitCode = 1;
}
