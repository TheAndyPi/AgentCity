import { test, expect } from "./fixtures";
import { randomUUID } from "node:crypto";
import { select3DCitizen } from "./world-selection";

for (const variant of [
  { theme: "dark", width: 1440, height: 900 },
  { theme: "light", width: 390, height: 844 },
] as const) {
  test(`low camera angles and ground panning retain the city in ${variant.theme} ${variant.width}px`, async ({
    page,
  }, info) => {
    await page.setViewportSize({
      width: variant.width,
      height: variant.height,
    });
    const session = (await (await page.request.get("/api/v1/session")).json())
      .data;
    const api = async (path: string, method = "GET", data?: unknown) => {
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
    };
    const { version, ...settings } = await api("/settings");
    await api("/settings", "PUT", {
      expected_version: version,
      settings: {
        ...settings,
        theme: variant.theme,
        view_mode: "3d",
        reduce_motion: true,
      },
    });
    const city = await api("/simulations", "POST", {
      config: { name: "Low camera", seed: 73, population: 10 },
    });
    await expect
      .poll(async () => (await api(`/simulations/${city.id}`)).status)
      .toBe("paused");
    await page.goto(`/simulations/${city.id}`);
    const canvas = page.locator(".world-wrap canvas");
    await expect(canvas).toBeVisible();
    const world = await api(`/simulations/${city.id}/state`);
    await select3DCitizen(page, world.agents[0].position);
    await expect(
      page.getByRole("heading", { name: world.agents[0].name, exact: true }),
    ).toBeVisible();
    const view = () =>
      page.evaluate(async () => {
        const sources = performance
          .getEntriesByType("resource")
          .filter((e) => e.name.includes("/@react-three_fiber.js"))
          .map((e) => e.name)
          .reverse();
        const canvas = document.querySelector(".world-wrap canvas");
        for (const source of sources) {
          const { _roots } = await import(source);
          const state = _roots?.get(canvas)?.store?.getState();
          if (!state?.controls || !state.scene.getObjectByName("city-ground"))
            continue;
          const { camera, controls } = state;
          const ground = state.scene.getObjectByName("city-ground").children[0];
          const { width, height, depth } = ground.geometry.parameters;
          let nearest = Infinity,
            farthest = -Infinity;
          for (const x of [-width / 2, width / 2])
            for (const y of [-height / 2, height / 2])
              for (const z of [-depth / 2, depth / 2]) {
                const point = camera.position
                  .clone()
                  .set(x, y, z)
                  .applyMatrix4(ground.matrixWorld)
                  .applyMatrix4(camera.matrixWorldInverse);
                nearest = Math.min(nearest, -point.z);
                farthest = Math.max(farthest, -point.z);
              }
          return {
            position: camera.position.toArray(),
            target: controls.target.toArray(),
            near: camera.near,
            far: camera.far,
            nearest,
            farthest,
            polar: controls.getPolarAngle(),
          };
        }
        return null;
      });
    await expect.poll(view).not.toBeNull();
    const box = (await canvas.boundingBox())!;
    const x = box.x + box.width * 0.8;
    await page.mouse.move(x, box.y + box.height * 0.75);
    await page.mouse.down();
    await page.mouse.move(x, box.y + box.height * 0.3, { steps: 16 });
    await page.mouse.up();
    const low = (await view())!;
    expect(low.polar).toBeGreaterThan(1.5);
    await page.screenshot({ path: info.outputPath("low-angle.png") });
    await page.mouse.move(x, box.y + box.height * 0.7);
    await page.mouse.down({ button: "right" });
    await page.mouse.move(x, box.y + box.height * 0.4, { steps: 16 });
    await page.mouse.up({ button: "right" });
    const panned = (await view())!;
    await info.attach("camera-bounds", {
      body: JSON.stringify({ low, panned }, null, 2),
      contentType: "application/json",
    });
    await page.screenshot({ path: info.outputPath("panned-ground.png") });
    expect(panned.target[1]).toBeCloseTo(low.target[1], 5);
    expect(low.nearest).toBeGreaterThanOrEqual(low.near);
    expect(panned.nearest).toBeGreaterThanOrEqual(panned.near);
    expect(panned.farthest).toBeLessThanOrEqual(panned.far);
  });
}
