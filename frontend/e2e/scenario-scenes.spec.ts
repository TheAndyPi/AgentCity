import { test, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
import type { Settings, WorldFrame } from "../src/api/types";

// Exercise actual R3F geometry, event lifecycle, and persisted scene payloads.
test("composed scenario has an orbitable preview and active 3D props", async ({
  page,
}, info) => {
  const session = (await (await page.request.get("/api/v1/session")).json())
    .data;
  const { version, ...settings }: Settings = (
    await (await page.request.get("/api/v1/settings")).json()
  ).data;
  const saved = await page.request.put("/api/v1/settings", {
    data: {
      expected_version: version,
      settings: { ...settings, view_mode: "3d" },
    },
    headers: {
      "X-CSRF-Token": session.csrf_token,
      "Idempotency-Key": randomUUID(),
    },
  });
  expect(saved.ok(), await saved.text()).toBeTruthy();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/simulations/new");
  await page.getByLabel("Simulation name").fill(`Scenario scene ${Date.now()}`);
  await page
    .getByLabel("Scenario description")
    .fill(
      "Dinosaurs and an alien spacecraft arrive during a festival for 2 ticks",
    );
  await page
    .getByRole("button", { name: "Create simulation", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("Confirm opening event");
  const diorama = page.locator(".scenario-diorama");
  await expect(diorama).toHaveAttribute("data-scene-models", /dinosaur/);
  await expect(diorama).toHaveAttribute("data-scene-models", /spacecraft/);
  await expect(diorama).toHaveAttribute("data-scene-models", /stage/);
  await expect(diorama.locator("canvas")).toBeVisible();
  // Wait for a rendered frame, rather than merely checking the canvas container.
  await expect
    .poll(() =>
      diorama
        .locator("canvas")
        .evaluate((canvas: HTMLCanvasElement) => canvas.width),
    )
    .toBeGreaterThan(0);
  await page.screenshot({
    path: info.outputPath("scenario-diorama.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(diorama.locator("canvas")).toBeVisible();
  expect((await diorama.boundingBox())!.width).toBeLessThan(390);
  await page.screenshot({
    path: info.outputPath("scenario-diorama-narrow.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  const sid = page.url().match(/simulations\/([^/]+)/)![1];
  const state = async (): Promise<WorldFrame> =>
    (await (await page.request.get(`/api/v1/simulations/${sid}/state`)).json())
      .data;
  const before = await state();
  const planned = before.simulation.initial_preview!.spec.scene!;
  expect(new Set(planned.map((o) => o.model))).toEqual(
    new Set(["dinosaur", "spacecraft", "stage"]),
  );
  await page
    .getByRole("button", { name: "Confirm opening event", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Step one tick", exact: true })
    .click();
  await expect
    .poll(async () => (await state()).events[0].status)
    .toBe("active");
  await expect(page.locator(".scenario-world-label")).toHaveCount(3);
  await page.screenshot({
    path: info.outputPath("scenario-in-city.png"),
    fullPage: true,
  });
  const active = await state();
  expect(active.events[0].scene).toEqual(planned);
  await page.reload();
  await expect(page.locator(".scenario-world-label")).toHaveCount(3);
  for (let i = 0; i < 2; i++) {
    await page
      .getByRole("button", { name: "Step one tick", exact: true })
      .click();
    await expect.poll(async () => (await state()).ref.tick).toBe(i + 2);
  }
  await expect
    .poll(async () => (await state()).events[0].status)
    .toBe("resolved");
  await expect(page.locator(".scenario-world-label")).toHaveCount(0);
  expect((await state()).events[0].scene).toEqual(planned);
  expect(errors).toEqual([]);
});

test("free-form primitive geometry renders on the GPU and can be orbited", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/tests/visual/scenario.html");
  const preview = page.getByRole("img", { name: "3D scenario preview: Whale" });
  await expect(preview.locator("canvas")).toBeVisible();
  const before = await preview.screenshot();
  const box = (await preview.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 100, box.y + box.height / 2, {
    steps: 10,
  });
  await page.mouse.up();
  await expect
    .poll(async () => !(await preview.screenshot()).equals(before))
    .toBe(true);
  await page.screenshot({ path: info.outputPath("generated-whale-scene.png") });
  expect(errors).toEqual([]);
});
