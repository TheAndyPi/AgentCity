import { randomUUID } from "node:crypto";
import { test, expect, type Page } from "../e2e/fixtures";
import type { Simulation } from "../src/api/types";

test.use({ isolatedOrigins: ["http://127.0.0.1:15175"] });

test("committed history reaches real observation API and matching browser graph through offline warehouse", async ({
  page,
}, info) => {
  async function api<T>(path: string, body?: unknown): Promise<T> {
    const session = await (await page.request.get("/api/v1/session")).json();
    const key = randomUUID();
    const response = await page.request.fetch(`/api/v1${path}`, {
      method: body ? "POST" : "GET",
      data: body,
      headers: {
        "X-CSRF-Token": session.data.csrf_token,
        "Idempotency-Key": key,
      },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
    return (await response.json()).data;
  }
  const city = await api<Simulation>("/simulations", {
    config: { name: "Observation worker browser", seed: 42, population: 10 },
  });
  await expect
    .poll(async () => (await api<Simulation>(`/simulations/${city.id}`)).status)
    .toBe("paused");
  const initial = await api<Simulation>(`/simulations/${city.id}`);
  // Use a separate request key matching the command body.
  const session = await (await page.request.get("/api/v1/session")).json();
  const key = randomUUID();
  const stepped = await page.request.post(
    `/api/v1/simulations/${city.id}/commands`,
    {
      data: {
        request_id: key,
        expected_control_version: initial.control_version,
        command: { type: "step", count: 2 },
      },
      headers: {
        "X-CSRF-Token": session.data.csrf_token,
        "Idempotency-Key": key,
      },
    },
  );
  expect(stepped.ok(), await stepped.text()).toBeTruthy();
  const current = await api<Simulation>(`/simulations/${city.id}`);
  const prefix = `/integrations/snowflake/observations/v1/simulations/${city.id}`;
  await expect
    .poll(
      async () =>
        (await api<{ ingested_revision: number }>(`${prefix}/status`))
          .ingested_revision,
    )
    .toBe(current.revision);
  const backend = await api<{
    items: { tick: number; mean: number; denominator: number }[];
  }>(`${prefix}/trends?through_revision=${current.revision}&metric=health`);
  expect(backend.items.length).toBeGreaterThan(0);

  await page.goto(`/simulations/${city.id}`);
  await page
    .getByRole("button", { name: "Open city menu", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Simulation overview", exact: true })
    .click();
  await page.getByRole("button", { name: "Observations", exact: true }).click();
  const panel = page.locator(".observations-panel");
  await expect(panel.getByRole("img")).toBeVisible();
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await panel.getByText(/Trend data table ·/).click();
  const table = panel
    .getByRole("table")
    .filter({
      has: page.getByRole("columnheader", { name: "Mean", exact: true }),
    });
  for (const point of backend.items) {
    const row = table
      .getByRole("row")
      .filter({
        has: page.getByRole("rowheader", {
          name: String(point.tick),
          exact: true,
        }),
      });
    const expected = Number.isInteger(point.mean)
      ? String(point.mean)
      : point.mean.toFixed(2);
    await expect(row.getByRole("cell").nth(0)).toHaveText(expected);
    await expect(row.getByRole("cell").nth(3)).toHaveText(
      String(point.denominator),
    );
  }
  await panel
    .getByLabel("Measure", { exact: true })
    .selectOption("relationship_trust");
  await expect(panel.getByRole("img")).toHaveAccessibleName(
    /Relationship trust/,
  );
  await page.screenshot({
    path: info.outputPath("observations-worker-api.png"),
    fullPage: true,
  });
});
