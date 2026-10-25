import { randomUUID } from "node:crypto";
import { test, expect, type Page } from "./fixtures";
import type { Settings, Simulation, WorldFrame } from "../src/api/types";
import type { DisasterState } from "../src/disasters/client";

async function api<T>(
  page: Page,
  path: string,
  method = "GET",
  data?: unknown,
): Promise<T> {
  const session = (await (await page.request.get("/api/v1/session")).json())
    .data;
  const response = await page.request.fetch("/api/v1" + path, {
    method,
    data,
    headers: {
      "X-CSRF-Token": session.csrf_token,
      "Idempotency-Key":
        (data as { request_id?: string })?.request_id ?? randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()).data;
}

for (const kind of [
  "flood",
  "fire",
  "storm",
  "earthquake",
  "tornado",
] as const) {
  test(`${kind} damage keeps the live 3D city and controls visible`, async ({
    page,
  }, info) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.stack ?? error.message));
    const { version, ...settings } = await api<Settings>(page, "/settings");
    await api(page, "/settings", "PUT", {
      expected_version: version,
      settings: { ...settings, view_mode: "3d", reduce_motion: true },
    });
    const city = await api<Simulation>(page, "/simulations", "POST", {
      config: {
        name: `${kind} rendering regression`,
        population: 10,
        seed: 42,
      },
    });
    const simulation = () => api<Simulation>(page, `/simulations/${city.id}`);
    const state = () => api<WorldFrame>(page, `/simulations/${city.id}/state`);
    const disasterBase = `/integrations/disasters/v2/simulations/${city.id}`;
    const disasters = () => api<DisasterState>(page, disasterBase + "/state");
    const step = async () =>
      api(page, `/simulations/${city.id}/commands`, "POST", {
        request_id: randomUUID(),
        expected_control_version: (await simulation()).control_version,
        command: { type: "step", count: 1 },
      });
    await expect.poll(async () => (await simulation()).status).toBe("paused");
    await page.goto(`/simulations/${city.id}`);
    await expect(page.locator(".world-wrap canvas")).toBeVisible();
    const frame = await state();
    const hold = await api<{ id: string; control_version: number }>(
      page,
      `/simulations/${city.id}/interventions`,
      "POST",
      {
        expected_control_version: (await simulation()).control_version,
      },
    );
    const preview = await api<{ preview: { id: string } }>(
      page,
      disasterBase + "/previews",
      "POST",
      {
        intervention_id: hold.id,
        parameters: {
          kind,
          intensity: {
            flood: 5,
            fire: 100,
            storm: 75,
            earthquake: 9,
            tornado: 130,
          }[kind],
          extent_m: Math.hypot(frame.map.width_m, frame.map.height_m),
          origin: { x: frame.map.width_m / 2, y: frame.map.height_m / 2 },
          track_end:
            kind === "tornado"
              ? { x: frame.map.width_m * 0.75, y: frame.map.height_m / 2 }
              : null,
          duration_ticks: 4,
          seed: 42,
          rule_version: "disasters-2.0.0",
        },
      },
    );
    await api(page, disasterBase + "/commits", "POST", {
      intervention_id: hold.id,
      preview_id: preview.preview.id,
      expected_control_version: hold.control_version,
    });
    for (let tick = 1; tick <= 2; tick++) {
      await step();
      await expect.poll(async () => (await state()).ref.tick).toBe(tick);
      await expect(page.locator(".live-voices")).toHaveAttribute(
        "data-sound-events",
        "1",
      );
      await page.screenshot({
        path: info.outputPath(`${kind}-tick-${tick}.png`),
        fullPage: true,
      });
      expect(errors).toEqual([]);
      const labels = page.locator(".damage-label");
      await expect.poll(() => labels.count()).toBeGreaterThan(0);
      for (const label of await labels.all()) {
        const box = (await label.boundingBox())!;
        expect(
          box.width,
          "A damage label must not cover the city",
        ).toBeLessThan(300);
        expect(box.height).toBeLessThan(40);
      }
      await expect(page.locator(".world-wrap canvas")).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Step one tick", exact: true }),
      ).toBeVisible();
      await page
        .getByRole("button", { name: "Step one tick", exact: true })
        .click({ trial: true });
    }
    expect((await disasters()).damage.length).toBeGreaterThan(0);
    await page.reload();
    await expect(page.locator(".world-wrap canvas")).toBeVisible();
    await expect(page.locator(".live-voices")).toHaveAttribute(
      "data-sound-events",
      "1",
    );
    expect(errors).toEqual([]);
  });
}
