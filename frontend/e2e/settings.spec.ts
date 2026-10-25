import { test, expect, type Page, type Request } from "@playwright/test";
import { defaultSettings } from "../src/api/defaults";
import type { Settings } from "../src/api/types";

const settingsPath = "**/api/v1/settings";
let previousSettings: Settings | undefined;
const isSave = (request: Request) =>
  request.url().endsWith("/api/v1/settings") && request.method() === "PUT";
const saveButton = (page: Page) =>
  page.getByRole("button", { name: "Save shortcuts", exact: true });
const nextButton = (page: Page) =>
  page.getByRole("button", {
    name: "Save and create a new simulation",
    exact: true,
  });
const pauseSelect = (page: Page) =>
  page.getByRole("combobox", { name: "Pause shortcut", exact: true });

async function settings(page: Page): Promise<Settings> {
  const response = await page.request.get("/api/v1/settings");
  expect(response.ok()).toBeTruthy();
  return (await response.json()).data;
}

async function update(page: Page, current: Settings, patch: Partial<Settings>) {
  const session = await page.request.get("/api/v1/session");
  const { version, ...values } = current;
  const response = await page.request.put("/api/v1/settings", {
    headers: {
      "X-CSRF-Token": (await session.json()).data.csrf_token,
      "Idempotency-Key": crypto.randomUUID(),
    },
    data: { expected_version: version, settings: { ...values, ...patch } },
  });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).data as Settings;
}

function saves(page: Page) {
  const requests: {
    key: string;
    body: { expected_version: number; settings: Omit<Settings, "version"> };
  }[] = [];
  page.on("request", (request) => {
    if (isSave(request))
      requests.push({
        key: request.headers()["idempotency-key"],
        body: request.postDataJSON(),
      });
  });
  return requests;
}

test.beforeEach(async ({ page }) => {
  // Every test sets its own shortcuts and display preferences and creates no cities.
  previousSettings = undefined;
  previousSettings = await settings(page);
  const { version: _, ...values } = defaultSettings;
  await update(page, previousSettings, {
    ...values,
    view_mode: "2d",
    reduce_motion: true,
  });
  const loaded = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/v1/settings") && r.request().method() === "GET",
  );
  await page.goto("/settings");
  await (await loaded).finished();
  await expect(page.locator("html")).toHaveAttribute("data-motion", "reduced");
  await expect(pauseSelect(page)).toHaveValue("Space");
});

test.afterEach(async ({ page }) => {
  if (!previousSettings) return;
  const { version: _, ...values } = previousSettings;
  await update(page, await settings(page), values);
});

test("successful shortcut save ends its operation before save and create", async ({
  page,
}) => {
  const initial = await settings(page),
    requests = saves(page);
  await pauseSelect(page).selectOption("KeyP");
  const first = page.waitForResponse((r) => isSave(r.request()));
  await saveButton(page).click();
  expect((await first).status()).toBe(200);
  await expect(saveButton(page)).toBeDisabled();
  const second = page.waitForResponse((r) => isSave(r.request()));
  await nextButton(page).click();
  expect((await second).status()).toBe(200);
  await expect(page).toHaveURL(/\/simulations\/new$/);
  expect(requests).toHaveLength(2);
  expect(requests[1].key).not.toBe(requests[0].key);
  expect(requests.map((r) => r.body.expected_version)).toEqual([
    initial.version,
    initial.version + 1,
  ]);
  expect((await settings(page)).shortcuts.pause).toBe("KeyP");
});

for (const loss of ["connection", "json", "contract"] as const) {
  test(`retry after ${loss} response loss replays the exact request without duplicate mutation`, async ({
    page,
  }) => {
    const initial = await settings(page),
      requests = saves(page);
    let drop = true;
    await page.route(settingsPath, async (route) => {
      if (!isSave(route.request()) || !drop) return route.continue();
      drop = false;
      const committed = await route.fetch();
      expect(committed.status()).toBe(200);
      if (loss === "connection") await route.abort("failed");
      else
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body:
            loss === "json"
              ? "lost response"
              : JSON.stringify({
                  schema_version: "1.0.0",
                  request_id: "lost",
                  data: {},
                }),
        });
    });
    await pauseSelect(page).selectOption("KeyP");
    await saveButton(page).click();
    await expect(
      page.getByText(
        /Cannot reach the AgentCity server|did not return a JSON contract|Response does not match contract/,
      ),
    ).toBeVisible();
    expect((await settings(page)).version).toBe(initial.version + 1);
    await nextButton(page).click();
    await expect(page).toHaveURL(/\/simulations\/new$/);
    expect(requests).toHaveLength(2);
    expect(requests[1]).toEqual(requests[0]);
    const saved = await settings(page);
    expect(saved.version).toBe(initial.version + 1);
    expect(saved.shortcuts.pause).toBe("KeyP");
  });
}

test("appearance saves queued before shortcuts use successive versions and preserve all edits", async ({
  page,
}) => {
  const initial = await settings(page),
    requests = saves(page);
  let release!: () => void, started!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const entered = new Promise<void>((resolve) => {
    started = resolve;
  });
  let first = true;
  await page.route(settingsPath, async (route) => {
    if (isSave(route.request()) && first) {
      first = false;
      started();
      await held;
    }
    await route.continue();
  });
  try {
    await pauseSelect(page).selectOption("KeyP");
    await page.getByRole("button", { name: "Light pastel" }).click();
    await entered;
    await page.getByRole("button", { name: "3D city", exact: true }).click();
    await nextButton(page).click();
    await expect(nextButton(page)).toBeDisabled();
    expect(requests).toHaveLength(1);
    release();
    await expect(page).toHaveURL(/\/simulations\/new$/);
    expect(requests).toHaveLength(3);
    expect(new Set(requests.map((r) => r.key)).size).toBe(3);
    expect(requests.map((r) => r.body.expected_version)).toEqual([
      initial.version,
      initial.version + 1,
      initial.version + 2,
    ]);
    expect(requests[0].body.settings.view_mode).toBe("2d");
    expect(requests[1].body.settings.shortcuts.pause).toBe("Space");
    expect(await settings(page)).toMatchObject({
      theme: "light",
      view_mode: "3d",
      shortcuts: { pause: "KeyP" },
    });
  } finally {
    release();
  }
});

test("appearance queued behind a lost shortcut response retries it before applying its own patch", async ({
  page,
}) => {
  const initial = await settings(page),
    requests = saves(page);
  let first = true;
  await page.route(settingsPath, async (route) => {
    if (!isSave(route.request()) || !first) return route.continue();
    first = false;
    expect((await route.fetch()).status()).toBe(200);
    await route.abort("failed");
  });
  await pauseSelect(page).selectOption("KeyP");
  await saveButton(page).click();
  await expect(
    page.getByText(/Cannot reach the AgentCity server/),
  ).toBeVisible();
  const appearance = page.waitForResponse(
    (r) =>
      isSave(r.request()) &&
      r.request().postDataJSON().settings.theme === "light",
  );
  await page.getByRole("button", { name: "Light pastel" }).click();
  expect((await appearance).status()).toBe(200);
  expect(requests).toHaveLength(3);
  expect(requests[1]).toEqual(requests[0]);
  expect(requests[2].key).not.toBe(requests[0].key);
  expect(requests[2].body.expected_version).toBe(initial.version + 1);
  expect(await settings(page)).toMatchObject({
    version: initial.version + 2,
    theme: "light",
    shortcuts: { pause: "KeyP" },
  });
  await nextButton(page).click();
  await expect(page).toHaveURL(/\/simulations\/new$/);
});

test("stale settings refresh the version and preserve the shortcut draft for retry", async ({
  page,
}) => {
  const initial = await settings(page),
    requests = saves(page);
  await update(page, initial, { theme: "light" });
  await pauseSelect(page).selectOption("KeyP");
  const conflict = page.waitForResponse((r) => isSave(r.request()));
  await saveButton(page).click();
  expect((await conflict).status()).toBe(409);
  await expect(page.getByText("Settings version is stale")).toBeVisible();
  await expect(pauseSelect(page)).toHaveValue("KeyP");
  await nextButton(page).click();
  await expect(page).toHaveURL(/\/simulations\/new$/);
  expect(requests[1].key).not.toBe(requests[0].key);
  expect(requests[1].body.expected_version).toBe(initial.version + 1);
  expect(await settings(page)).toMatchObject({
    version: initial.version + 2,
    theme: "light",
    shortcuts: { pause: "KeyP" },
  });
});
