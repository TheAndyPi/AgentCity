import { mkdtempSync } from "node:fs";
import { join } from "node:path";
import {
  backend,
  frontend,
  localEnv,
  npmArgs,
  python,
  spawnProcess,
  stopProcess,
  temp,
} from "./runtime.mjs";
const isBackend = process.argv[2] === "backend";
const child = spawnProcess(
  isBackend ? python : process.execPath,
  isBackend
    ? [
        "-m",
        "uvicorn",
        "behavior_browser_app:create_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        "10840",
      ]
    : npmArgs(["run", "dev", "--", "--port", "15176", "--strictPort"]),
  {
    cwd: isBackend ? backend : frontend,
    env: {
      ...localEnv,
      PYTHONPATH: "tests",
      DATA_DIR: isBackend ? mkdtempSync(join(temp, "behavior-e2e-")) : "unused",
      AUTH_MODE: "local",
      LLM_MODE: "rules",
      ENABLE_NARRATION: "false",
      TIGER_ENABLED: "false",
      SNOWFLAKE_ENABLED: "false",
      SNOWFLAKE_OBSERVATIONS_ENABLED: "false",
      ALLOWED_ORIGINS: "http://127.0.0.1:15176,http://127.0.0.1:10840",
      AGENTCITY_BACKEND_URL: "http://127.0.0.1:10840",
    },
  },
);
for (const signal of ["SIGTERM", "SIGINT"])
  process.on(signal, () => void stopProcess(child));
child.on("exit", (code) => process.exit(code ?? 0));
