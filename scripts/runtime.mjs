import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { createServer } from "node:net";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseEnv } from "node:util";

export const root = fileURLToPath(new URL("../", import.meta.url));
export const backend = join(root, "backend");
export const frontend = join(root, "frontend");
export const python =
  process.env.AGENTCITY_PYTHON ||
  join(
    backend,
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
export const temp = join(backend, ".tmp");
mkdirSync(temp, { recursive: true });
export const localEnv = {
  ...process.env,
  TEMP: temp,
  TMP: temp,
  npm_config_cache: join(temp, "npm-cache"),
};

export function backendEnv(extra = {}) {
  const file = join(backend, ".env");
  const defaults = existsSync(file) ? parseEnv(readFileSync(file, "utf8")) : {};
  return { ...defaults, ...localEnv, ...extra };
}

export function npmArgs(args) {
  const cli =
    process.env.npm_execpath ||
    join(dirname(process.execPath), "node_modules/npm/bin/npm-cli.js");
  if (!existsSync(cli))
    throw new Error(
      "Run this command through npm, or install npm alongside Node.js.",
    );
  return [cli, ...args];
}

export function run(command, args, { cwd = root, env = localEnv } = {}) {
  const result = spawnSync(command, args, {
    cwd,
    env,
    stdio: "inherit",
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0)
    throw new Error(`${command} exited with status ${result.status}`);
}

export function spawnProcess(
  command,
  args,
  { cwd = root, env = localEnv, stdio = "inherit" } = {},
) {
  return spawn(command, args, { cwd, env, stdio, windowsHide: true });
}

export async function stopProcess(child) {
  if (!child || child.exitCode !== null || !child.pid) return;
  if (process.platform === "win32") {
    // Only a child started by this launcher is targeted; never kill by process name.
    spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
      stdio: "ignore",
      windowsHide: true,
    });
  } else {
    child.kill("SIGTERM");
    await Promise.race([
      new Promise((resolve) => child.once("exit", resolve)),
      new Promise((resolve) => setTimeout(resolve, 5000)),
    ]);
    if (child.exitCode === null) child.kill("SIGKILL");
  }
}

export async function freePort(port, host = "127.0.0.1") {
  await new Promise((resolve, reject) => {
    const socket = createServer();
    socket.once("error", () =>
      reject(
        new Error(
          `Port ${port} is already in use. Choose PORT/FRONTEND_PORT or stop the existing server.`,
        ),
      ),
    );
    socket.listen(port, host, () => socket.close(resolve));
  });
}

export async function waitFor(url, child, seconds = 30) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    if (child?.exitCode !== null && child?.exitCode !== undefined)
      throw new Error(`Server exited before ${url} became ready.`);
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(1500) });
      if (response.ok) return;
    } catch {
      /* Keep waiting for the process to bind its port. */
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for ${url}`);
}

export function checkedPort(value, fallback) {
  const port = Number(value || fallback);
  if (!Number.isInteger(port) || port < 1 || port > 65535)
    throw new Error("Ports must be integers between 1 and 65535.");
  return port;
}

export function requireInstall() {
  if (
    !existsSync(python) ||
    !existsSync(join(frontend, "node_modules/vite/bin/vite.js"))
  )
    throw new Error("Dependencies are missing. Run npm run setup first.");
}

export function absoluteDataDir(value) {
  return resolve(backend, value || "data");
}
