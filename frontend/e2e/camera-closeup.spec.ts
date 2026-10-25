import { randomUUID } from "node:crypto";
import { test, expect, type Page } from "./fixtures";
import { select3DCitizen } from "./world-selection";
import type { Settings, Simulation, WorldFrame } from "../src/api/types";

type Mode = "2d" | "3d";

async function view(page: Page, mode: Mode): Promise<number[] | null> {
  if (mode === "2d") {
    const box = await page.locator("svg.world-2d").getAttribute("viewBox");
    return box ? box.split(" ").map(Number) : null;
  }
  return page.evaluate(async () => {
    const sources = performance
      .getEntriesByType("resource")
      .filter((entry) => entry.name.includes("/@react-three_fiber.js"))
      .map((entry) => entry.name)
      .reverse();
    const canvas = document.querySelector(".world-wrap canvas");
    for (const source of sources) {
      const { _roots } = await import(source);
      const state = _roots?.get(canvas)?.store?.getState();
      if (!state?.controls) continue;
      return [
        ...state.camera.position.toArray(),
        ...state.controls.target.toArray(),
        ...state.camera.quaternion.toArray(),
        state.camera.zoom,
      ];
    }
    return null;
  });
}

async function settledView(page: Page, mode: Mode) {
  let previous: number[] | null = null;
  await expect
    .poll(async () => {
      const current = await view(page, mode);
      const still =
        current &&
        previous &&
        current.every((value, i) => Math.abs(value - previous![i]) < 0.001);
      previous = current;
      return !!still;
    })
    .toBe(true);
  return previous!;
}

async function expectSameView(page: Page, mode: Mode, before: number[]) {
  await expect
    .poll(async () => {
      const current = await view(page, mode);
      return !!current?.every((value, i) => Math.abs(value - before[i]) < 0.05);
    })
    .toBe(true);
}

async function setup(page: Page, mode: Mode) {
  const session = (await (await page.request.get("/api/v1/session")).json())
    .data;
  async function api<T>(
    path: string,
    method = "GET",
    data?: unknown,
  ): Promise<T> {
    const response = await page.request.fetch("/api/v1" + path, {
      method,
      data,
      headers: {
        "X-CSRF-Token": session.csrf_token,
        "Idempotency-Key": randomUUID(),
      },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
    return (await response.json()).data;
  }
  const { version, ...settings } = await api<Settings>("/settings");
  await api("/settings", "PUT", {
    expected_version: version,
    settings: { ...settings, view_mode: mode, reduce_motion: false },
  });
  const city = await api<Simulation>("/simulations", "POST", {
    config: { name: "Camera controls", seed: 73, population: 10 },
  });
  await expect
    .poll(async () => (await api<Simulation>(`/simulations/${city.id}`)).status)
    .toBe("paused");
  const world = await api<WorldFrame>(`/simulations/${city.id}/state`);
  await page.goto(`/simulations/${city.id}`);
  const surface = page.locator(
    mode === "3d" ? ".world-wrap canvas" : "svg.world-2d",
  );
  await expect(surface).toBeVisible();
  const wide = await settledView(page, mode);
  const agent = world.agents[0];
  const select = () =>
    mode === "3d"
      ? select3DCitizen(page, agent.position)
      : surface
          .getByRole("button", {
            name: `${agent.name}, ${agent.role}`,
            exact: true,
          })
          .click();
  await select();
  const focus = page.getByRole("complementary", { name: "Character focus" });
  await expect(focus).toBeVisible();
  return { surface, focus, select, wide };
}

for (const mode of ["3d", "2d"] as const) {
  test(`repeated clicks keep the ${mode} close-up and following active`, async ({
    page,
  }) => {
    const { surface, focus, select, wide } = await setup(page, mode);
    // Click while the camera is still arriving, then repeatedly once it is close.
    const box = (await surface.boundingBox())!;
    await surface.click({
      position: { x: box.width * 0.94, y: box.height * 0.45 },
      clickCount: 6,
      delay: 35,
    });
    await expect(focus).toBeVisible();
    await expect(
      page.getByText("Following citizen · pan to stop"),
    ).toBeVisible();
    const close = await settledView(page, mode);
    if (mode === "3d") expect(close[10]).toBeGreaterThan(wide[10] * 1.5);
    else expect(close[2]).toBeLessThan(wide[2]);
    await surface.click({
      position: { x: box.width * 0.94, y: box.height * 0.45 },
      clickCount: 6,
      delay: 35,
    });
    await expectSameView(page, mode, close);

    if (mode === "3d") {
      await page
        .getByRole("button", { name: "Rotate left", exact: true })
        .click();
      await page.getByRole("button", { name: "Zoom in", exact: true }).click();
    }
    const adjusted = await settledView(page, mode);
    for (let i = 0; i < 3; i++) await select();
    await expect(focus).toBeVisible();
    await expectSameView(page, mode, adjusted);

    // A real drag still hands camera control to the user without closing details.
    await page.mouse.move(box.x + box.width * 0.8, box.y + box.height * 0.6);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.8, box.y + box.height * 0.4, {
      steps: 12,
    });
    await page.mouse.up();
    await expect(
      page.getByText("Following citizen · pan to stop"),
    ).not.toBeVisible();
    await expect(focus).toBeVisible();
  });

  test(`closing ${mode} details preserves framing until an explicit overview action`, async ({
    page,
  }, info) => {
    const { focus, select } = await setup(page, mode);
    await settledView(page, mode);
    await page.getByRole("button", { name: "Zoom in", exact: true }).click();
    const before = await settledView(page, mode);
    await focus.getByRole("button", { name: "Close character focus" }).click();
    await expect(focus).not.toBeVisible();
    await expectSameView(page, mode, before);
    await page.screenshot({
      path: info.outputPath(`${mode}-dismissed-closeup.png`),
    });

    await select();
    const refocused = await settledView(page, mode);
    await page.keyboard.press("Escape");
    await expect(focus).not.toBeVisible();
    await expectSameView(page, mode, refocused);

    await page
      .getByRole("button", { name: "Reset camera", exact: true })
      .click();
    const reset = await settledView(page, mode);
    if (mode === "3d") expect(reset[10]).toBeLessThan(refocused[10] / 1.5);
    else expect(reset[2]).toBeGreaterThan(refocused[2] * 1.5);

    await select();
    await settledView(page, mode);
    await page.getByRole("button", { name: "Back to neighborhood" }).click();
    await expect(focus).not.toBeVisible();
    await expectSameView(page, mode, reset);
  });
}
