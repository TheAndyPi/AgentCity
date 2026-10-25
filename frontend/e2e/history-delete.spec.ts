import { randomUUID } from "node:crypto";
import { test, expect, type Page } from "./fixtures";
import type { Simulation } from "../src/api/types";

async function api<T>(
  page: Page,
  path: string,
  method = "GET",
  data?: unknown,
): Promise<T> {
  const session = await page.request.get("/api/v1/session");
  const response = await page.request.fetch(`/api/v1${path}`, {
    method,
    data,
    headers: {
      "X-CSRF-Token": (await session.json()).data.csrf_token,
      "Idempotency-Key":
        (data as { request_id?: string })?.request_id ?? randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()).data;
}

async function create(page: Page, name: string) {
  const city = await api<Simulation>(page, "/simulations", "POST", {
    config: { name, seed: 42, population: 10 },
  });
  await expect
    .poll(
      async () =>
        (await api<Simulation>(page, `/simulations/${city.id}`)).status,
    )
    .toBe("paused");
  return city;
}

async function command(page: Page, id: string, type: "archive" | "play") {
  const city = await api<Simulation>(page, `/simulations/${id}`);
  return api(page, `/simulations/${id}/commands`, "POST", {
    request_id: randomUUID(),
    expected_control_version: city.control_version,
    command: { type },
  });
}

test("a running save can be deleted directly; cancelling does not archive or delete it", async ({
  page,
}) => {
  const city = await create(page, "Old running save");
  const keeper = await create(page, "Keep this save");
  await command(page, city.id, "play");
  await page.goto("/simulations");
  const remove = page.getByRole("button", {
    name: `Delete ${city.name}`,
    exact: true,
  });
  await remove.click();
  let dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(city.name);
  await expect(dialog.getByRole("textbox")).toHaveCount(0);
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  const unchanged = await api<Simulation>(page, `/simulations/${city.id}`);
  expect(unchanged.archived).toBe(false);
  expect(unchanged.status).toBe("running");
  await remove.click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByRole("button", { name: "Delete save", exact: true })
    .click();
  await expect(dialog).toHaveCount(0);
  expect(
    (await page.request.get(`/api/v1/simulations/${city.id}`)).status(),
  ).toBe(404);
  expect(
    (await page.request.get(`/api/v1/simulations/${keeper.id}`)).status(),
  ).toBe(200);
  await page.reload();
  await expect(
    page.getByRole("button", { name: `Delete ${keeper.name}`, exact: true }),
  ).toBeVisible();
  await expect(remove).toHaveCount(0);
});

test("mobile bulk deletion keeps a failed save selected and retries only that save", async ({
  page,
}) => {
  const city = await create(page, "Old active save");
  const archived = await create(page, "Old archived save");
  const keeper = await create(page, "Keep the other save");
  await command(page, archived.id, "archive");
  let fail = true;
  await page.route(`**/api/v1/simulations/${archived.id}`, async (route) => {
    if (route.request().method() !== "DELETE" || !fail) return route.continue();
    fail = false;
    await route.fulfill({
      status: 503,
      json: {
        schema_version: "1.0.0",
        request_id: route.request().headers()["idempotency-key"],
        error: {
          code: "SERVICE_UNAVAILABLE",
          message: "Temporary deletion failure",
          retryable: true,
          details: [],
        },
      },
    });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/simulations");
  await page
    .getByRole("checkbox", { name: `Select ${city.name}`, exact: true })
    .check();
  await page
    .getByRole("checkbox", { name: `Select ${archived.name}`, exact: true })
    .check();
  await page
    .getByRole("button", { name: "Delete selected (2)", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("button", { name: "Delete 2 saves", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText("1 deleted. 1 failed");
  await expect(dialog.locator(".delete-save-list li")).toHaveText([
    archived.name,
  ]);
  expect(
    (await page.request.get(`/api/v1/simulations/${city.id}`)).status(),
  ).toBe(404);
  expect(
    (await api<Simulation>(page, `/simulations/${archived.id}`)).archived,
  ).toBe(true);
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(
    page.getByRole("checkbox", {
      name: `Select ${archived.name}`,
      exact: true,
    }),
  ).toBeChecked();
  await page
    .getByRole("button", { name: "Delete selected (1)", exact: true })
    .click();
  await dialog
    .getByRole("button", { name: "Delete save", exact: true })
    .click();
  await expect(dialog).toHaveCount(0);
  expect(
    (await page.request.get(`/api/v1/simulations/${archived.id}`)).status(),
  ).toBe(404);
  expect(
    (await page.request.get(`/api/v1/simulations/${keeper.id}`)).status(),
  ).toBe(200);
});

test("select all includes active and archived saves and deletes them with one confirmation", async ({
  page,
}) => {
  const city = await create(page, "Select all active save");
  const archived = await create(page, "Select all archived save");
  await command(page, archived.id, "archive");
  await page.goto("/simulations");
  const all = page.getByRole("checkbox", {
    name: "Select all saves",
    exact: true,
  });
  await expect(
    page.getByRole("button", { name: "Delete selected", exact: true }),
  ).toBeDisabled();
  await all.check();
  await expect(
    page.getByRole("checkbox", { name: `Select ${city.name}`, exact: true }),
  ).toBeChecked();
  await expect(
    page.getByRole("checkbox", {
      name: `Select ${archived.name}`,
      exact: true,
    }),
  ).toBeChecked();
  await page
    .getByRole("checkbox", { name: `Select ${city.name}`, exact: true })
    .uncheck();
  await expect(all).not.toBeChecked();
  await all.check();
  await page
    .getByRole("button", { name: "Delete selected (2)", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Delete 2 saves", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  for (const id of [city.id, archived.id])
    expect((await page.request.get(`/api/v1/simulations/${id}`)).status()).toBe(
      404,
    );
  await expect(
    page.getByRole("heading", { name: "No simulations yet", exact: true }),
  ).toBeVisible();
});
