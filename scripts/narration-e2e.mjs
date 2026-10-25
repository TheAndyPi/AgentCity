import { mkdtempSync, rmSync } from "node:fs";
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

// Real AgentCity backend and Vite proxy; only the ElevenLabs HTTP endpoint is faked.
const isBackend = process.argv[2] === "backend";
const dataDir = isBackend ? mkdtempSync(join(temp, "narration-e2e-")) : null;
const child = spawnProcess(
  isBackend ? python : process.execPath,
  isBackend
    ? [
        "-m",
        "uvicorn",
        "narration_browser_app:create_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        "10830",
      ]
    : npmArgs(["run", "dev", "--", "--port", "15175", "--strictPort"]),
  {
    cwd: isBackend ? backend : frontend,
    env: {
      ...localEnv,
      PYTHONPATH: "tests",
      DATA_DIR: dataDir ?? "unused",
      AUTH_MODE: "local",
      LLM_MODE: "rules",
      ENABLE_NARRATION: "false",
      TIGER_ENABLED: "false",
      SNOWFLAKE_ENABLED: "false",
      CHOKIDAR_USEPOLLING: "true",
      ALLOWED_ORIGINS: "http://127.0.0.1:15175,http://127.0.0.1:10830",
      AGENTCITY_BACKEND_URL: "http://127.0.0.1:10830",
    },
  },
);
for (const signal of ["SIGTERM", "SIGINT"])
  process.on(signal, () => void stopProcess(child));
child.on("exit", (code) => {
  if (dataDir) rmSync(dataDir, { recursive: true, force: true });
  process.exit(code ?? 0);
});
