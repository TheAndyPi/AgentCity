import { backend, backendEnv, python, run } from "./runtime.mjs";

// Without --live this only checks configuration. Explicit --live may synthesize
// two short committed lines using two real authorized citizen voices.
try {
  run(python, ["-m", "scripts.live_voices_smoke", ...process.argv.slice(2)], {
    cwd: backend,
    env: backendEnv(),
  });
} catch { process.exitCode = 1; }
