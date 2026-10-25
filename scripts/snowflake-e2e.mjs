import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import {
  backend,
  frontend,
  localEnv,
  npmArgs,
  python,
  temp,
} from "./runtime.mjs";
const isBackend = process.argv[2] === "backend";
const dataDir = isBackend ? mkdtempSync(join(temp, "snowflake-e2e-")) : null;
const child = spawn(
  isBackend ? python : process.execPath,
  isBackend
    ? [
        "-m",
        "uvicorn",
        "snowflake_browser_app:create_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        "10820",
      ]
    : npmArgs(["run", "dev", "--", "--port", "15174"]),
  {
    cwd: isBackend ? backend : frontend,
    env: {
      ...localEnv,
      PYTHONPATH: "tests",
      DATA_DIR: dataDir ?? "unused",
      AUTH_MODE: "local",
      LLM_MODE: "rules",
      ALLOWED_ORIGINS: "http://127.0.0.1:15174,http://127.0.0.1:10820",
      AGENTCITY_BACKEND_URL: "http://127.0.0.1:10820",
    },
    stdio: "inherit",
  },
);
for (const signal of ["SIGTERM", "SIGINT"])
  process.on(signal, () => child.kill(signal));
child.on("exit", (code) => {
  if (dataDir) rmSync(dataDir, { recursive: true, force: true });
  process.exit(code ?? 0);
});
