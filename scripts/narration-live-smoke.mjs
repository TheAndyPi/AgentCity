import { backend, backendEnv, python, run } from "./runtime.mjs";

// Paid opt-in: one real ElevenLabs synthesis through the real application routes.
const live = process.argv.includes("--live");
if (!live)
  throw new Error(
    "Explicit paid opt-in required: node scripts/narration-live-smoke.mjs --live [--save path.mp3]",
  );
try {
  run(python, ["-m", "scripts.narration_smoke", ...process.argv.slice(2)], {
    cwd: backend,
    env: backendEnv(),
  });
} catch {
  process.exitCode = 1;
}
