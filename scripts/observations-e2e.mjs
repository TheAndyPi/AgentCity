import { mkdtempSync } from "node:fs";
import { join } from "node:path";
import {
  backend,
  frontend,
  localEnv,
  npmArgs,
  python,
  spawnProcess,
  temp,
} from "./runtime.mjs";

const isBackend = process.argv[2] === "backend";
const child = spawnProcess(
  isBackend ? python : process.execPath,
  isBackend
    ? [
        "-m",
        "uvicorn",
        "observations_browser_app:create_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        "10821",
      ]
    : npmArgs(["run", "dev", "--", "--port", "15175"]),
  {
    cwd: isBackend ? backend : frontend,
    env: {
      ...localEnv,
      PYTHONPATH: "tests",
      DATA_DIR: isBackend
        ? mkdtempSync(join(temp, "observations-e2e-"))
        : "unused",
      AUTH_MODE: "local",
      LLM_MODE: "rules",
      TIGER_ENABLED: "false",
      SNOWFLAKE_ENABLED: "false",
      SNOWFLAKE_OBSERVATIONS_ENABLED: "false",
      ENABLE_NARRATION: "false",
      ALLOWED_ORIGINS: "http://127.0.0.1:15175,http://127.0.0.1:10821",
      AGENTCITY_BACKEND_URL: "http://127.0.0.1:10821",
    },
  },
);
for (const signal of ["SIGINT", "SIGTERM"])
  process.on(signal, () => child.kill(signal));
child.on("exit", (code) => process.exit(code ?? 0));
