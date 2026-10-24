import { existsSync } from "node:fs";
import {
  backend,
  frontend,
  localEnv,
  npmArgs,
  python,
  root,
  run,
} from "./runtime.mjs";

try {
  if (!existsSync(python))
    run(
      process.env.PYTHON ||
        (process.platform === "win32" ? "python" : "python3"),
      ["-m", "venv", `${backend}/.venv`],
    );
  run(python, [
    "-c",
    "import sys; assert sys.version_info >= (3,13), 'Python 3.13 or newer is required'",
  ]);
  run(python, ["-m", "ensurepip", "--upgrade"]);
  run(python, ["-m", "pip", "install", "-r", "requirements.lock"], {
    cwd: backend,
  });
  run(
    process.execPath,
    npmArgs(["ci", "--prefix", frontend, "--no-audit", "--no-fund"]),
    { cwd: root, env: localEnv },
  );
  console.log(
    "\nAgentCity is ready. Run npm run dev for the live application.",
  );
} catch (error) {
  console.error(`Setup: ${error.message}`);
  process.exitCode = 1;
}
