import { existsSync } from "node:fs";
import { join } from "node:path";
import {
  backend,
  backendEnv,
  checkedPort,
  freePort,
  frontend,
  python,
  spawnProcess,
  stopProcess,
  waitFor,
} from "./runtime.mjs";

let server;
for (const signal of ["SIGINT", "SIGTERM"])
  process.on(signal, () => void stopProcess(server));
try {
  const dist = join(frontend, "dist");
  if (!existsSync(join(dist, "index.html")))
    throw new Error("Build the frontend first with npm run build.");
  const env = backendEnv({ FRONTEND_DIST: dist });
  const port = checkedPort(env.PORT, 8000);
  env.ALLOWED_ORIGINS ||= `http://127.0.0.1:${port},http://localhost:${port}`;
  await freePort(port);
  server = spawnProcess(python, ["-m", "app"], { cwd: backend, env });
  server.on("error", (error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
  server.on("exit", (code) => {
    process.exitCode = code || 0;
  });
  await waitFor(`http://127.0.0.1:${port}/health/ready`, server, 300);
  console.log(
    `\nAgentCity: http://127.0.0.1:${port} (frontend, API and WebSocket on one origin)\n`,
  );
} catch (error) {
  console.error(`AgentCity startup: ${error.message}`);
  await stopProcess(server);
  process.exitCode = 1;
}
