import { join } from "node:path";
import {
  backend,
  backendEnv,
  checkedPort,
  freePort,
  frontend,
  localEnv,
  python,
  requireInstall,
  spawnProcess,
  stopProcess,
  waitFor,
} from "./runtime.mjs";

const mock = process.argv.includes("--mock");
const children = [];
let stopping = false;
async function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  await Promise.all(children.map(stopProcess));
  process.exitCode = code;
}
for (const signal of ["SIGINT", "SIGTERM"])
  process.on(signal, () => void stop());

try {
  requireInstall();
  const env = backendEnv();
  const apiPort = checkedPort(env.PORT, 8000);
  const uiPort = checkedPort(process.env.FRONTEND_PORT, 5173);
  await freePort(uiPort);
  if (!mock) {
    await freePort(apiPort);
    const origins =
      env.ALLOWED_ORIGINS ||
      [
        `http://127.0.0.1:${uiPort}`,
        `http://localhost:${uiPort}`,
        `http://127.0.0.1:${apiPort}`,
        `http://localhost:${apiPort}`,
      ].join(",");
    const api = spawnProcess(python, ["-m", "app"], {
      cwd: backend,
      env: {
        ...env,
        HOST: "127.0.0.1",
        PORT: String(apiPort),
        FRONTEND_DIST: "",
        ALLOWED_ORIGINS: origins,
      },
    });
    children.push(api);
    api.on("error", (error) => {
      console.error(error.message);
      void stop(1);
    });
    api.once("exit", () => {
      if (!stopping) void stop(1);
    });
    await waitFor(`http://127.0.0.1:${apiPort}/health/ready`, api, 300);
  }
  const ui = spawnProcess(
    process.execPath,
    [
      join(frontend, "node_modules/vite/bin/vite.js"),
      "--host",
      "127.0.0.1",
      "--port",
      String(uiPort),
      "--strictPort",
    ],
    {
      cwd: frontend,
      env: {
        ...localEnv,
        VITE_DATA_MODE: mock ? "mock" : "live",
        AGENTCITY_BACKEND_URL: `http://127.0.0.1:${apiPort}`,
      },
    },
  );
  children.push(ui);
  ui.on("error", (error) => {
    console.error(error.message);
    void stop(1);
  });
  ui.once("exit", () => {
    if (!stopping) void stop(1);
  });
  await waitFor(`http://127.0.0.1:${uiPort}`, ui);
  console.log(
    `\nAgentCity ${mock ? "MOCK REVIEW" : "LIVE"}: http://127.0.0.1:${uiPort}\nPress Ctrl+C to stop.\n`,
  );
} catch (error) {
  console.error(`AgentCity startup: ${error.message}`);
  await stop(1);
}
