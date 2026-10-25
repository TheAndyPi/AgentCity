import { test, expect, type Page } from "./fixtures";
import { randomUUID } from "node:crypto";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  writeFileSync,
} from "node:fs";
import { resolve } from "node:path";
import * as THREE from "three";
import type { Simulation, WorldFrame, Settings } from "../src/api/types";

const artifactDirectory = resolve("artifacts/integration");
mkdirSync(resolve(artifactDirectory, "screenshots"), { recursive: true });
test.afterEach(async ({}, info) => {
  if (info.status !== "passed" || !existsSync(info.outputDir)) return;
  for (const entry of readdirSync(info.outputDir)) {
    if (entry.endsWith(".png"))
      copyFileSync(
        resolve(info.outputDir, entry),
        resolve(artifactDirectory, "screenshots", entry),
      );
  }
});

async function api<T>(
  page: Page,
  path: string,
  method = "GET",
  data?: unknown,
): Promise<T> {
  const origin = page.url().startsWith("http")
    ? new URL(page.url()).origin
    : "";
  const session = await page.request.get(`${origin}/api/v1/session`);
  const csrf = (await session.json()).data.csrf_token;
  const key = (data as { request_id?: string })?.request_id || randomUUID();
  const response = await page.request.fetch(`${origin}/api/v1${path}`, {
    method,
    data,
    headers: { "X-CSRF-Token": csrf, "Idempotency-Key": key },
  });
  expect(
    response.ok(),
    `${method} ${path}: ${await response.text()}`,
  ).toBeTruthy();
  return (await response.json()).data;
}

async function command(
  page: Page,
  id: string,
  action: Record<string, unknown>,
) {
  const simulation = await api<Simulation>(page, `/simulations/${id}`);
  return api(page, `/simulations/${id}/commands`, "POST", {
    request_id: randomUUID(),
    expected_control_version: simulation.control_version,
    command: action,
  });
}

async function preferences(page: Page, values: Partial<Settings>) {
  const current = await api<Settings>(page, "/settings");
  const { version, ...settings } = current;
  await api(page, "/settings", "PUT", {
    expected_version: version,
    settings: { ...settings, ...values },
  });
}

test("real create, initial flood, stream, inspector, outcome, undo and saved history", async ({
  page,
}, info) => {
  const errors: string[] = [];
  const writes: unknown[] = [];
  const pendingWrites: Promise<void>[] = [];
  page.on("response", (response) => {
    const request = response.request();
    if (request.method() === "GET" || !response.url().includes("/api/v1/"))
      return;
    pendingWrites.push(
      (async () => {
        try {
          writes.push({
            method: request.method(),
            path: new URL(response.url()).pathname,
            idempotency_key: request.headers()["idempotency-key"],
            request: request.postDataJSON(),
            status: response.status(),
            response: await response.json(),
          });
        } catch {
          /* Aborted transport responses have no body. */
        }
      })(),
    );
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await preferences(page, { view_mode: "2d", reduce_motion: true });
  await page.goto("/simulations/new");
  const name = `Live integration ${Date.now()}`;
  await page.getByLabel("Simulation name").fill(name);
  await page
    .getByRole("slider", { name: "Number of agents", exact: true })
    .fill("10");
  await expect(
    page.getByRole("slider", { name: "Number of agents", exact: true }),
  ).toHaveValue("10");
  await page
    .getByLabel("Scenario description")
    .fill("A flood severity 60 for 2 ticks");
  await page
    .getByRole("button", { name: "Create simulation", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("Confirm opening event");
  const id = page.url().match(/simulations\/([^/]+)/)![1];
  const initial = await api<WorldFrame>(page, `/simulations/${id}/state`);
  expect(initial.agents).toHaveLength(10);
  expect(initial.simulation.tick).toBe(0);
  await expect(page.locator(".mock-badge")).toHaveCount(0);
  await expect(page.locator(".connection")).toHaveText("LIVE");
  await page.screenshot({
    path: info.outputPath("live-initial-preview.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Confirm opening event", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const queued = await api<WorldFrame>(page, `/simulations/${id}/state`);
  expect(queued.events[0].status).toBe("queued");
  expect(queued.simulation.status).toBe("paused");
  for (let tick = 1; tick <= 3; tick++) {
    await page
      .getByRole("button", { name: "Step one tick", exact: true })
      .click();
    await expect
      .poll(
        async () => (await api<Simulation>(page, `/simulations/${id}`)).tick,
      )
      .toBe(tick);
  }
  await expect(page.getByRole("dialog")).toContainText("Event outcome");
  const outcome = await api<WorldFrame>(page, `/simulations/${id}/state`);
  expect(outcome.simulation.pause_reason).toBe("outcome");
  expect(outcome.simulation.pending_outcome_event_ids).toHaveLength(1);
  await page.screenshot({
    path: info.outputPath("live-outcome.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect((await api<Simulation>(page, `/simulations/${id}`)).status).toBe(
    "paused",
  );
  await page
    .getByRole("button", { name: "Find a citizen", exact: true })
    .click();
  await page.getByRole("button", { name: /^Open .* profile$/ }).click();
  await page.getByRole("tab", { name: "Story", exact: true }).click();
  await expect(page.getByRole("complementary")).toContainText(
    "Why this action",
  );
  await page.screenshot({
    path: info.outputPath("live-inspector.png"),
    fullPage: true,
  });
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");

  // A second resolved report is undone through the actual UI into a new lineage.
  await page
    .getByRole("button", { name: "Introduce an event", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("textbox")
    .fill("A festival for 1 tick");
  await page.getByRole("button", { name: /Preview/ }).click();
  await page
    .getByRole("button", { name: "Confirm event", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  for (let tick = 4; tick <= 5; tick++) {
    await page
      .getByRole("button", { name: "Step one tick", exact: true })
      .click();
    await expect
      .poll(
        async () => (await api<Simulation>(page, `/simulations/${id}`)).tick,
      )
      .toBe(tick);
  }
  await expect(page.getByRole("dialog")).toContainText("Event outcome");
  await page.getByRole("button", { name: /Undo event/ }).click();
  await expect(page).not.toHaveURL(new RegExp(`/simulations/${id}$`));
  await expect(page.locator(".connection")).toHaveText("LIVE");
  const branchId = page.url().match(/simulations\/([^/]+)/)![1];
  expect(branchId).not.toBe(id);
  const restored = await api<WorldFrame>(
    page,
    `/simulations/${branchId}/state`,
  );
  expect(restored.simulation.parent_simulation_id).toBe(id);
  expect(restored.simulation.status).toBe("paused");
  expect(restored.simulation.tick).toBe(3);
  expect(
    (await api<WorldFrame>(page, `/simulations/${id}/state`)).events,
  ).toHaveLength(2);
  await page
    .getByRole("button", { name: "Open city menu", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Previous simulations", exact: true })
    .click();
  await expect(page).toHaveURL(/\/simulations$/);
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  const saved = await api<Simulation>(page, `/simulations/${branchId}`);
  expect(saved.saved_at).not.toBeNull();
  expect(errors).toEqual([]);
  await Promise.all(pendingWrites);
  writeFileSync(
    resolve(artifactDirectory, "live-request-response.json"),
    JSON.stringify(
      {
        contract_version: "1.0.0",
        mode: "live",
        decision_engine: "rules",
        writes,
      },
      null,
      2,
    ),
  );
  await info.attach("real-api-trace", {
    body: JSON.stringify(writes),
    contentType: "application/json",
  });
});

test("built frontend, HTTP API and WebSocket work on one production origin", async ({
  page,
}, info) => {
  const failures: string[] = [];
  page.on("pageerror", (e) => failures.push(e.message));
  await page.goto("http://127.0.0.1:10801");
  await preferences(page, { view_mode: "2d" });
  const city = await api<Simulation>(page, "/simulations", "POST", {
    config: { name: "Built same-origin city", seed: 34, population: 10 },
  });
  await expect
    .poll(
      async () =>
        (await api<Simulation>(page, `/simulations/${city.id}`)).status,
    )
    .toBe("paused");
  await page.goto(`http://127.0.0.1:10801/simulations/${city.id}`);
  await expect(page.locator(".connection")).toHaveText("LIVE");
  await page
    .getByRole("button", { name: "Step one tick", exact: true })
    .click();
  await expect
    .poll(
      async () => (await api<Simulation>(page, `/simulations/${city.id}`)).tick,
    )
    .toBe(1);
  await page.reload();
  await expect(page.locator(".connection")).toHaveText("LIVE");
  await expect(page.locator(".mock-badge")).toHaveCount(0);
  await expect(page.locator(".city-name")).toContainText(city.name);
  await page.screenshot({
    path: info.outputPath("built-same-origin.png"),
    fullPage: true,
  });
  expect(failures).toEqual([]);
});

test("replay excludes initialization, and a continued branch saves before browser Back", async ({
  page,
}) => {
  await preferences(page, { view_mode: "2d" });
  const created = await api<Simulation>(page, "/simulations", "POST", {
    config: { name: "Exact historical browser", seed: 11, population: 10 },
  });
  await expect
    .poll(
      async () =>
        (await api<Simulation>(page, `/simulations/${created.id}`)).status,
    )
    .toBe("paused");
  const ready = await api<Simulation>(page, `/simulations/${created.id}`);
  await command(page, created.id, { type: "step", count: 3 });
  await page.goto(`/simulations/${created.id}`);
  await expect(page.locator(".connection")).toHaveText("LIVE");
  await page
    .getByRole("button", { name: "Rewind recorded history", exact: true })
    .click();
  await expect(page.locator(".replay-bar")).toBeVisible();
  await page
    .getByRole("slider", { name: "Committed history revision" })
    .focus();
  await page.keyboard.press("Home");
  await expect(page.locator(".replay-bar")).toContainText(
    `Revision ${ready.revision}`,
  );
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Continue from here", exact: true })
    .click();
  await expect(page).not.toHaveURL(new RegExp(`/simulations/${created.id}$`));
  await expect(page.locator(".connection")).toHaveText("LIVE");
  const branchId = page.url().match(/simulations\/([^/]+)/)![1];
  await page
    .getByRole("button", { name: "Play simulation", exact: true })
    .click();
  await expect
    .poll(
      async () =>
        (await api<Simulation>(page, `/simulations/${branchId}`)).status,
    )
    .toBe("running");
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`/simulations/${created.id}$`));
  const saved = await api<Simulation>(page, `/simulations/${branchId}`);
  expect(saved.status).toBe("paused");
  const snapshots = await api<{ items: { reason: string }[] }>(
    page,
    `/simulations/${branchId}/snapshots`,
  );
  expect(snapshots.items.some((s) => s.reason === "navigation")).toBe(true);
});

test("citizen details remain readable during slow live refreshes and isolate changed selections", async ({
  page,
}) => {
  await preferences(page, { view_mode: "2d", reduce_motion: true });
  const city = await api<Simulation>(page, "/simulations", "POST", {
    config: {
      name: "Uninterrupted citizen inspector",
      seed: 11,
      population: 10,
    },
  });
  await expect
    .poll(
      async () =>
        (await api<Simulation>(page, `/simulations/${city.id}`)).status,
    )
    .toBe("paused");
  const ready = await api<Simulation>(page, `/simulations/${city.id}`);
  await page.goto(`/simulations/${city.id}`);
  await expect(page.locator(".connection")).toHaveText("LIVE");
  await page
    .getByRole("button", { name: "Find a citizen", exact: true })
    .click();
  await page.getByRole("button", { name: /^Open .* profile$/ }).click();
  const inspector = page.getByRole("complementary");
  await expect(
    inspector.getByRole("tab", { name: "Story", exact: true }),
  ).toBeVisible();
  await inspector.getByRole("tab", { name: "Mind", exact: true }).click();
  const initialRevision = Number(
    await inspector.locator(".agent-heading").getAttribute("data-revision"),
  );

  let requests = 0;
  await page.route(
    `**/api/v1/simulations/${city.id}/agents/*?*`,
    async (route) => {
      const request = ++requests;
      const response = await route.fetch();
      // Responses span multiple physical ticks and the first arrives out of order.
      await new Promise((resolve) =>
        setTimeout(resolve, request === 1 ? 1800 : 800),
      );
      await route.fulfill({ response });
    },
  );
  const continuity = await inspector
    .locator(".drawer-tabs")
    .evaluateHandle((tabs) => {
      const evidence = {
        loaderShown: false,
        tabsRemoved: false,
        rewound: false,
        revision: 0,
      };
      const drawer = tabs.closest(".drawer")!;
      const observer = new MutationObserver(() => {
        evidence.loaderShown ||= !!drawer.querySelector(".busy");
        evidence.tabsRemoved ||= !tabs.isConnected;
        const revision = Number(
          drawer.querySelector(".agent-heading")?.getAttribute("data-revision"),
        );
        evidence.rewound ||= revision < evidence.revision;
        evidence.revision = revision;
      });
      observer.observe(drawer, {
        subtree: true,
        childList: true,
        attributes: true,
      });
      return { evidence, stop: () => observer.disconnect() };
    });
  await page
    .getByRole("button", { name: "Play simulation", exact: true })
    .click();
  await expect.poll(() => requests).toBeGreaterThanOrEqual(6);
  await expect
    .poll(async () =>
      Number(
        await inspector.locator(".agent-heading").getAttribute("data-revision"),
      ),
    )
    .toBeGreaterThan(initialRevision + 2);
  await expect(
    inspector.getByRole("tab", { name: "Mind", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  const observed = await continuity.evaluate(({ evidence, stop }) => {
    stop();
    return evidence;
  });
  expect(observed).toMatchObject({
    loaderShown: false,
    tabsRemoved: false,
    rewound: false,
  });
  await continuity.dispose();

  await page
    .getByRole("button", { name: "Pause simulation", exact: true })
    .click();
  await inspector
    .getByRole("tab", { name: "Relationships", exact: true })
    .click();
  const previousName = await inspector
    .locator(".agent-heading h2")
    .textContent();
  await inspector.locator(".relationship-card button").first().click();
  await expect(inspector.locator(".agent-heading")).toHaveCount(0);
  await expect(inspector.locator(".agent-heading h2")).not.toHaveText(
    previousName!,
  );
  await expect(inspector.locator(".agent-heading")).toBeVisible();

  await page
    .getByRole("button", { name: "Rewind recorded history", exact: true })
    .click();
  await expect(page.locator(".replay-bar")).toBeVisible();
  // Entering replay intentionally closes the live inspector; open a historical one.
  await page
    .getByRole("button", { name: "Find a citizen", exact: true })
    .click();
  await page.getByRole("button", { name: /^Open .* profile$/ }).click();
  await expect(inspector.locator(".agent-heading")).toBeVisible();
  await page
    .getByRole("slider", { name: "Committed history revision" })
    .focus();
  await page.keyboard.press("Home");
  await expect(inspector.locator(".agent-heading")).toHaveCount(0);
  await expect(inspector.locator(".agent-heading")).toHaveAttribute(
    "data-revision",
    String(ready.revision),
  );
});

test("an ambiguous confirmed event response retries the same key exactly once", async ({
  page,
}) => {
  await preferences(page, { view_mode: "2d" });
  const city = await api<Simulation>(page, "/simulations", "POST", {
    config: { name: "Lost response city", seed: 8, population: 10 },
  });
  await expect
    .poll(
      async () =>
        (await api<Simulation>(page, `/simulations/${city.id}`)).status,
    )
    .toBe("paused");
  await page.goto(`/simulations/${city.id}`);
  await expect(page.locator(".connection")).toHaveText("LIVE");
  const keys: string[] = [];
  await page.route("**/scenario-commits", async (route) => {
    keys.push(route.request().headers()["idempotency-key"]);
    if (keys.length === 1) {
      await route.fetch();
      await route.abort("failed");
    } else await route.continue();
  });
  await page
    .getByRole("button", { name: "Introduce an event", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("textbox")
    .fill("A festival for 1 tick");
  await page.getByRole("button", { name: /Preview/ }).click();
  await page
    .getByRole("button", { name: "Confirm event", exact: true })
    .click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
    "CONNECTION_ERROR",
  );
  await page
    .getByRole("button", { name: "Confirm event", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  expect(
    (await api<WorldFrame>(page, `/simulations/${city.id}/state`)).events,
  ).toHaveLength(1);
  const snapshots = await api<{ items: { reason: string }[] }>(
    page,
    `/simulations/${city.id}/snapshots`,
  );
  expect(snapshots.items.filter((s) => s.reason === "pre_event")).toHaveLength(
    1,
  );
});

test("a manual pause from another tab invalidates preview and never auto-resumes", async ({
  page,
}) => {
  await preferences(page, { view_mode: "2d" });
  const city = await api<Simulation>(page, "/simulations", "POST", {
    config: { name: "Control race city", seed: 4, population: 10 },
  });
  await expect
    .poll(
      async () =>
        (await api<Simulation>(page, `/simulations/${city.id}`)).status,
    )
    .toBe("paused");
  await page.goto(`/simulations/${city.id}`);
  await expect(page.locator(".connection")).toHaveText("LIVE");
  await page
    .getByRole("button", { name: "Play simulation", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Pause simulation", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Introduce an event", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("textbox")
    .fill("A flood for 1 tick");
  await page.getByRole("button", { name: /Preview/ }).click();
  await expect(
    page.getByRole("button", { name: "Confirm event", exact: true }),
  ).toBeEnabled();
  await command(page, city.id, { type: "pause" });
  await page
    .getByRole("button", { name: "Confirm event", exact: true })
    .click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
    "CONTROL_CONFLICT",
  );
  await expect(page.getByRole("dialog").getByRole("textbox")).toHaveValue(
    "A flood for 1 tick",
  );
  await page.getByRole("button", { name: /Preview/ }).click();
  await page
    .getByRole("button", { name: "Confirm event", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect((await api<Simulation>(page, `/simulations/${city.id}`)).status).toBe(
    "paused",
  );
});

test("running event editor pauses, cancels safely and resumes only the prior intent", async ({
  page,
}) => {
  await preferences(page, { view_mode: "2d" });
  const created = await api<Simulation>(page, "/simulations", "POST", {
    config: { name: "Live modal cancellation", seed: 93, population: 10 },
  });
  await expect
    .poll(
      async () =>
        (await api<Simulation>(page, `/simulations/${created.id}`)).status,
    )
    .toBe("paused");
  await page.goto(`/simulations/${created.id}`);
  await expect(page.locator(".connection")).toHaveText("LIVE");
  await page
    .getByRole("button", { name: "Play simulation", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Pause simulation", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Introduce an event", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("Simulation paused");
  const held = await api<Simulation>(page, `/simulations/${created.id}`);
  expect(held.status).toBe("paused");
  await page.waitForTimeout(650);
  expect((await api<Simulation>(page, `/simulations/${created.id}`)).tick).toBe(
    held.tick,
  );
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Cancel", exact: true })
    .click();
  await expect
    .poll(
      async () =>
        (await api<Simulation>(page, `/simulations/${created.id}`)).status,
    )
    .toBe("running");
  await page
    .getByRole("button", { name: "Pause simulation", exact: true })
    .click();
  await expect
    .poll(
      async () =>
        (await api<Simulation>(page, `/simulations/${created.id}`)).status,
    )
    .toBe("paused");
  await page
    .getByRole("button", { name: "Introduce an event", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("Simulation paused");
  await expect(
    page
      .getByRole("dialog")
      .getByRole("button", { name: "Cancel", exact: true }),
  ).toBeEnabled();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(
    (await api<Simulation>(page, `/simulations/${created.id}`)).status,
  ).toBe("paused");
});

test("three failed sockets fall back to real REST polling, then reconnect", async ({
  page,
}) => {
  await preferences(page, { view_mode: "2d" });
  const city = await api<Simulation>(page, "/simulations", "POST", {
    config: { name: "Real polling recovery", seed: 19, population: 10 },
  });
  await expect
    .poll(
      async () =>
        (await api<Simulation>(page, `/simulations/${city.id}`)).status,
    )
    .toBe("paused");
  let attempts = 0;
  await page.routeWebSocket("**/stream", (socket) => {
    attempts++;
    if (attempts <= 3) socket.close();
    else socket.connectToServer();
  });
  await page.goto(`/simulations/${city.id}`);
  await expect(page.locator(".connection")).toHaveText("POLLING");
  await command(page, city.id, { type: "step", count: 10 });
  await expect(page.locator(".sim-clock")).toContainText("00:01");
  await expect(page.locator(".connection")).toHaveText("LIVE");
  expect(attempts).toBeGreaterThanOrEqual(4);
});

test("failed navigation save keeps the running city and retries its original operation", async ({
  page,
}) => {
  await preferences(page, { view_mode: "2d" });
  const city = await api<Simulation>(page, "/simulations", "POST", {
    config: { name: "Save failure boundary", seed: 62, population: 10 },
  });
  await expect
    .poll(
      async () =>
        (await api<Simulation>(page, `/simulations/${city.id}`)).status,
    )
    .toBe("paused");
  await page.goto(`/simulations/${city.id}`);
  await expect(page.locator(".connection")).toHaveText("LIVE");
  await page
    .getByRole("button", { name: "Play simulation", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Pause simulation", exact: true }),
  ).toBeVisible();
  const keys: string[] = [];
  await page.route("**/commands", async (route) => {
    const request = route.request().postDataJSON();
    if (
      request.command.type === "save" &&
      request.command.reason === "navigation"
    ) {
      keys.push(request.request_id);
      if (keys.length === 1) {
        await route.fulfill({
          status: 503,
          json: {
            schema_version: "1.0.0",
            request_id: request.request_id,
            error: {
              code: "PERSISTENCE_UNAVAILABLE",
              message: "Injected navigation save failure",
              retryable: true,
              details: [],
            },
          },
        });
        return;
      }
    }
    await route.continue();
  });
  await page
    .getByRole("button", { name: "Open city menu", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Previous simulations", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "PERSISTENCE_UNAVAILABLE",
  );
  await expect(page).toHaveURL(new RegExp(`/simulations/${city.id}$`));
  expect((await api<Simulation>(page, `/simulations/${city.id}`)).status).toBe(
    "running",
  );
  await page
    .getByRole("button", { name: "Open city menu", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Previous simulations", exact: true })
    .click();
  await expect(page).toHaveURL(/\/simulations$/);
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  expect((await api<Simulation>(page, `/simulations/${city.id}`)).status).toBe(
    "paused",
  );
});

test("mobile settings and profiles preserve setup drafts, copy citizens, archive and delete", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/simulations/new");
  const name = `Mobile live city ${Date.now()}`;
  await page.getByLabel("Simulation name").fill(name);
  await page.getByRole("link", { name: /Create one in Settings/ }).click();
  await page
    .getByRole("button", { name: "Create custom agent", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("textbox", { name: "Name", exact: true })
    .fill("Aster integration");
  await page
    .getByRole("button", { name: "Save custom agent", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "2D map", exact: true }).click();
  await page.getByRole("button", { name: /Light pastel/ }).click();
  await page.getByRole("checkbox", { name: /Reduce motion/ }).check();
  await page
    .getByRole("button", {
      name: "Save and create a new simulation",
      exact: true,
    })
    .click();
  await expect(page.getByLabel("Simulation name")).toHaveValue(name);
  await expect(
    page.getByRole("slider", { name: "Number of agents", exact: true }),
  ).toHaveValue("10");
  await page.getByRole("checkbox", { name: /Aster integration/ }).check();
  await page
    .getByRole("button", { name: "Create simulation", exact: true })
    .click();
  await expect(page.locator(".connection")).toHaveText("LIVE");
  const id = page.url().match(/simulations\/([^/]+)/)![1];
  const frame = await api<WorldFrame>(page, `/simulations/${id}/state`);
  expect(frame.agents).toHaveLength(10);
  const citizen = frame.agents.find((a) => a.name === "Aster integration")!;
  expect(citizen).toBeDefined();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.locator("html")).toHaveAttribute("data-motion", "reduced");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("live-mobile-light-city.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Open city menu", exact: true })
    .click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page
    .getByRole("button", { name: "Edit Aster integration", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("textbox", { name: "Name", exact: true })
    .fill("Aster revised template");
  await page
    .getByRole("button", { name: "Save custom agent", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const detail = await api<{ profile: { name: string } }>(
    page,
    `/simulations/${id}/agents/${citizen.id}`,
  );
  expect(detail.profile.name).toBe("Aster integration");
  await page
    .getByRole("button", { name: "Delete Aster revised template", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Delete profile", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page
    .getByRole("link", { name: "Previous simulations", exact: true })
    .click();
  await page
    .getByRole("button", { name: `Archive ${name}`, exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: `Unarchive ${name}`, exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Permanently delete all", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("textbox", { name, exact: true })
    .fill(name);
  await page
    .getByRole("button", { name: "Permanently delete", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect((await page.request.get(`/api/v1/simulations/${id}`)).status()).toBe(
    404,
  );
});

test("dense mixed-use blocks have 3D hover tags and keyboard-accessible 2D purposes", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await preferences(page, {
    view_mode: "3d",
    reduce_motion: true,
    theme: "dark",
  });
  const city = await api<Simulation>(page, "/simulations", "POST", {
    config: {
      name: "Downtown neighborhoods",
      seed: 42,
      population: 80,
      environment: { settlement: "urban", population_density: 75 },
    },
  });
  await expect
    .poll(
      async () =>
        (await api<Simulation>(page, `/simulations/${city.id}`)).status,
    )
    .toBe("paused");
  const frame = await api<WorldFrame>(page, `/simulations/${city.id}/state`);
  expect(frame.agents).toHaveLength(80);
  expect(frame.map.buildings).toHaveLength(240);
  const blocks = new Map<string, number>();
  for (const building of frame.map.buildings) {
    const first = building.footprint[0],
      key = `${Math.floor(first.x / 16)}:${Math.floor(first.y / 16)}`;
    blocks.set(key, (blocks.get(key) ?? 0) + 1);
  }
  expect(blocks.size).toBe(64);
  expect([...blocks.values()].every((count) => count >= 2 && count <= 4)).toBe(
    true,
  );
  await page.goto(`/simulations/${city.id}?qa=1`);
  const viewport = page.getByRole("region", { name: /City viewport/ });
  await expect(viewport.locator("canvas")).toBeVisible();
  await expect(page.locator("[data-qa-fps]")).toContainText("FPS");
  const canvas = (await viewport.locator("canvas").boundingBox())!;
  const camera = new THREE.OrthographicCamera(
    -canvas.width / 2,
    canvas.width / 2,
    canvas.height / 2,
    -canvas.height / 2,
    0.1,
    1000,
  );
  camera.position.set(
    frame.map.width_m * 1.4,
    Math.max(frame.map.width_m, frame.map.height_m) * 1.2,
    frame.map.height_m * 1.45,
  );
  camera.zoom = 4.4;
  camera.lookAt(frame.map.width_m / 2, 0, frame.map.height_m / 2);
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld();
  const hoveredKinds = new Set<string>();
  for (const building of [...frame.map.buildings].reverse()) {
    if (hoveredKinds.has(building.kind)) continue;
    const xs = building.footprint.map((p) => p.x),
      ys = building.footprint.map((p) => p.y);
    const point = new THREE.Vector3(
      (Math.min(...xs) + Math.max(...xs)) / 2,
      building.height_m,
      (Math.min(...ys) + Math.max(...ys)) / 2,
    ).project(camera);
    const x = canvas.x + ((point.x + 1) * canvas.width) / 2,
      y = canvas.y + ((1 - point.y) * canvas.height) / 2;
    if (
      x < canvas.x ||
      x > canvas.x + canvas.width ||
      y < canvas.y ||
      y > canvas.y + canvas.height
    )
      continue;
    await page.mouse.move(x, y);
    const tag = page.locator(`[data-building-tooltip="${building.id}"]`);
    if (await tag.isVisible()) {
      await expect(tag).toContainText(building.name);
      await expect(tag).toContainText(`Capacity ${building.capacity}`);
      hoveredKinds.add(building.kind);
    }
    if (hoveredKinds.size >= 4) break;
  }
  expect(hoveredKinds.size).toBeGreaterThanOrEqual(4);
  await page.mouse.move(canvas.x + 5, canvas.y + 5);
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await page.screenshot({
    path: info.outputPath("dense-city-3d.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Test WebGL fallback", exact: true })
    .click();
  await expect(viewport.locator("[data-building-id]")).toHaveCount(
    frame.map.buildings.length,
  );
  const restaurant = frame.map.buildings.find((b) =>
    b.name.includes("Restaurant"),
  )!;
  const restaurantShape = viewport.locator(
    `[data-building-id="${restaurant.id}"]`,
  );
  await restaurantShape.hover();
  await expect(page.getByRole("tooltip")).toContainText("Restaurant");
  await expect(page.getByRole("tooltip")).toContainText(restaurant.name);
  await page.mouse.move(canvas.x + 5, canvas.y + 5);
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  const hospital = frame.map.buildings.find((b) => b.kind === "hospital")!;
  await viewport.locator(`[data-building-id="${hospital.id}"]`).focus();
  await expect(page.getByRole("tooltip")).toContainText(hospital.name);
  await page.screenshot({
    path: info.outputPath("dense-city-2d-purpose-tag.png"),
    fullPage: true,
  });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  expect(errors).toEqual([]);
});

for (const population of [30, 100])
  test(`real ${population}-citizen 3D world responds while running and supports WebGL fallback`, async ({
    page,
  }, info) => {
    await preferences(page, {
      view_mode: "3d",
      reduce_motion: true,
      theme: "dark",
    });
    const city = await api<Simulation>(page, "/simulations", "POST", {
      config: { name: `3D live ${population}`, seed: 39, population },
    });
    await expect
      .poll(
        async () =>
          (await api<Simulation>(page, `/simulations/${city.id}`)).status,
      )
      .toBe("paused");
    await page.goto(`/simulations/${city.id}?qa=1`);
    await expect(page.locator(".connection")).toHaveText("LIVE");
    const viewport = page.getByRole("region", { name: /City viewport/ });
    await expect(viewport.locator("canvas,svg.world-2d")).toBeVisible();
    await page
      .getByRole("button", { name: "Play simulation", exact: true })
      .click();
    await expect
      .poll(
        async () =>
          (await api<Simulation>(page, `/simulations/${city.id}`)).tick,
      )
      .toBeGreaterThanOrEqual(4);
    const running = await api<WorldFrame>(
      page,
      `/simulations/${city.id}/state`,
    );
    const walkableAt = (point: { x: number; y: number }) =>
      running.map.cells.find(
        (cell) =>
          cell.col === Math.floor(point.x / running.map.cell_size_m) &&
          cell.row === Math.floor(point.y / running.map.cell_size_m),
      )?.walkable;
    const indoors = (point: { x: number; y: number }) =>
      running.map.buildings.some((building) => {
        const xs = building.footprint.map((p) => p.x);
        const ys = building.footprint.map((p) => p.y);
        return (
          point.x >= Math.min(...xs) &&
          point.x <= Math.max(...xs) &&
          point.y >= Math.min(...ys) &&
          point.y <= Math.max(...ys)
        );
      });
    const reachable = (point: { x: number; y: number }) =>
      walkableAt(point) === true || indoors(point);
    expect(
      running.agents.filter((agent) => !reachable(agent.position)),
    ).toEqual([]);
    expect(
      running.agents
        .flatMap((agent) => agent.path)
        .filter((point) => !reachable(point)),
    ).toEqual([]);
    const renderer = (await viewport.locator("canvas").count())
      ? "webgl"
      : "2d-fallback";
    let fps = "Unavailable: WebGL fallback active";
    if (renderer === "webgl") {
      await expect(page.locator("[data-qa-fps]")).toContainText("FPS");
      fps = (await page.locator("[data-qa-fps]").textContent())!;
    }
    await info.attach("real-running-renderer", {
      body: JSON.stringify({
        population,
        renderer,
        fps,
        runtime: "Chrome headless on Windows; local real API",
      }),
      contentType: "application/json",
    });
    await page
      .getByRole("button", { name: "Pause simulation", exact: true })
      .click();
    await page.screenshot({
      path: info.outputPath(`real-${population}-citizens.png`),
      fullPage: true,
    });
    if (renderer === "webgl")
      await page
        .getByRole("button", { name: "Test WebGL fallback", exact: true })
        .click();
    await expect(viewport.locator("svg.world-2d")).toBeVisible();
    await expect(viewport.locator('[data-ground="roads"] rect')).toHaveCount(
      running.map.cells.filter((cell) => cell.terrain === "road").length,
    );
    await expect(
      viewport.locator('[data-ground="sidewalks"] rect').first(),
    ).toBeVisible();
    await expect(
      viewport.locator('[data-ground="markings"] rect').first(),
    ).toBeVisible();
    await page.screenshot({
      path: info.outputPath(`city-ground-2d-${population}.png`),
      fullPage: true,
    });
    const agent = (await api<WorldFrame>(page, `/simulations/${city.id}/state`))
      .agents[0];
    await viewport
      .getByRole("button", {
        name: `${agent.name}, ${agent.role}`,
        exact: true,
      })
      .focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("complementary")).toContainText(agent.name);
  });

test("life sim traits, conversations and open-ended events work on desktop and mobile", async ({
  page,
}, info) => {
  await preferences(page, { view_mode: "2d", reduce_motion: true });
  const city = await api<Simulation>(page, "/simulations", "POST", {
    config: { name: "Life sim UI review", seed: 19, population: 10 },
  });
  await expect
    .poll(
      async () =>
        (await api<Simulation>(page, `/simulations/${city.id}`)).status,
    )
    .toBe("paused");
  const frame = await api<WorldFrame>(page, `/simulations/${city.id}/state`);
  const [a, b] = frame.agents;
  const dialogue = [
    {
      id: "dialogue_00000001",
      interaction_id: "conversation-test",
      tick: 1,
      speaker_id: a.id,
      recipient_ids: [b.id],
      text: "Did you see the mysterious visitor?",
      end_conversation: false,
    },
    {
      id: "dialogue_00000002",
      interaction_id: "conversation-test",
      tick: 1,
      speaker_id: b.id,
      recipient_ids: [a.id],
      text: "Yes! I wonder what brought them here.",
      end_conversation: false,
    },
    {
      id: "dialogue_00000003",
      interaction_id: "conversation-test",
      tick: 2,
      speaker_id: a.id,
      recipient_ids: [b.id],
      text: "Let's ask them together.",
      end_conversation: true,
    },
  ].map((message) => ({
    ...message,
    audible_to_ids: [a.id, b.id],
    emotion: "curious",
    intent: "talk",
  }));
  await page.route(`**/api/v1/simulations/${city.id}/dialogue?*`, (route) =>
    route.fulfill({
      json: {
        schema_version: "1.0.0",
        request_id: randomUUID(),
        data: { items: [...dialogue].reverse(), next_cursor: null },
      },
    }),
  );
  await page.goto(`/simulations/${city.id}`);
  await page
    .getByRole("button", { name: "Agent traits 10", exact: true })
    .click();
  await expect(page.locator(".roster-grid button")).toHaveCount(10);
  await expect(page.getByRole("meter")).toHaveCount(6);
  await page.locator(".roster-grid button").nth(1).click();
  await expect(page.locator(".roster-profile h3").first()).toHaveText(b.name);
  await expect(page.getByRole("meter")).toHaveCount(6);
  await page.screenshot({
    path: info.outputPath("life-traits-desktop.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Close panel", exact: true })
    .last()
    .click();
  await page.getByRole("button", { name: /^Conversations/ }).click();
  const transcript = page.getByRole("region", {
    name: "Conversation transcript",
  });
  await expect(transcript).toContainText("Did you see the mysterious visitor?");
  await expect(transcript).toContainText(
    "Yes! I wonder what brought them here.",
  );
  await expect(page.locator(".speech-message strong")).toHaveText([
    a.name,
    b.name,
    a.name,
  ]);
  await page.screenshot({
    path: info.outputPath("life-conversations-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(transcript).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("life-conversations-mobile.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Close panel", exact: true })
    .last()
    .click();
  await page
    .getByRole("button", { name: "Agent traits 10", exact: true })
    .click();
  await expect(page.getByRole("meter")).toHaveCount(6);
  await page.getByLabel("Search citizens").fill(b.name);
  await expect(page.locator(".roster-grid button")).toHaveCount(1);
  await page.screenshot({
    path: info.outputPath("life-traits-mobile.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Close panel", exact: true })
    .last()
    .click();
  await page
    .getByRole("button", { name: "Introduce an event", exact: true })
    .click();
  await page
    .getByLabel("Describe your event")
    .fill("Dinosaurs appear in the town square");
  await page
    .getByRole("button", { name: "Preview event", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText(
    "Citizens learn about your event",
  );
  await expect(page.getByRole("dialog")).not.toContainText("Unsupported parts");
  await page.screenshot({
    path: info.outputPath("life-custom-event-mobile.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Confirm event", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const queued = await api<WorldFrame>(page, `/simulations/${city.id}/state`);
  expect(queued.events[0].title).toBe("Dinosaurs appear in the town square");
  expect(queued.events[0].status).toBe("queued");
});
