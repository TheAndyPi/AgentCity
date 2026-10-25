import { backend, backendEnv, python, run } from "./runtime.mjs";
try {
  run(python, ["-m", "scripts.disaster_audio_smoke", ...process.argv.slice(2)], { cwd: backend, env: backendEnv() });
} catch (error) {
  console.error(error.message);
  process.exitCode = 2;
}
