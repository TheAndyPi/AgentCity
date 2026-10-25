import { expect, type Page } from "@playwright/test";

// Canvas characters have no DOM hit target. Read the live renderer camera to
// project a real world position, then use an ordinary mouse click/raycaster.
// This never calls application selection handlers or changes production UI.
export async function select3DCitizen(
  page: Page,
  position: { x: number; y: number },
) {
  const canvas = page.locator(".world-wrap canvas");
  await expect(canvas).toBeVisible();
  const point = await page.evaluate(async (position) => {
    const source = performance
      .getEntriesByType("resource")
      .find((entry) => entry.name.includes("/@react-three_fiber.js"))?.name;
    if (!source) throw new Error("Live R3F renderer module was not loaded");
    const { _roots } = await import(source);
    const canvas =
      document.querySelector<HTMLCanvasElement>(".world-wrap canvas")!;
    const { camera } = _roots.get(canvas).store.getState();
    const point = camera.position
      .clone()
      .set(position.x, 1.14, position.y)
      .project(camera);
    const rect = canvas.getBoundingClientRect();
    return {
      x: rect.x + ((point.x + 1) / 2) * rect.width,
      y: rect.y + ((1 - point.y) / 2) * rect.height,
    };
  }, position);
  await page.mouse.click(point.x, point.y);
}
