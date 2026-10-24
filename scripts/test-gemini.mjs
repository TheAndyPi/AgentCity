import { backend, backendEnv, python, run } from "./runtime.mjs";

try {
  const module = process.argv.includes("--application")
    ? "scripts.gemini_application_smoke"
    : "scripts.gemini_smoke";
  run(python, ["-m", module], { cwd: backend, env: backendEnv() });
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
