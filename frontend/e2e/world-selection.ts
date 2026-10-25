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
  const target = { x: 0, y: 0 };
  await expect
    .poll(
      async () => {
        const point = await page.evaluate(async (position) => {
          const sources = [
            ...new Set(
              performance
                .getEntriesByType("resource")
                .filter((entry) =>
                  entry.name.includes("/@react-three_fiber.js"),
                )
                .map((entry) => entry.name),
            ),
          ].reverse();
          const canvas =
            document.querySelector<HTMLCanvasElement>(".world-wrap canvas");
          if (!canvas) return null;
          let renderer;
          for (const source of sources) {
            const { _roots } = await import(source);
            renderer = _roots?.get(canvas)?.store?.getState();
            if (renderer) break;
          }
          if (!renderer?.scene.getObjectByProperty("isInstancedMesh", true))
            return null;
          await new Promise<void>((resolve) =>
            requestAnimationFrame(() => resolve()),
          );
          const { camera } = renderer;
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
        if (!point) return false;
        Object.assign(target, point);
        return true;
      },
      { message: "The live renderer camera and citizen meshes become ready" },
    )
    .toBe(true);
  await page.mouse.click(target.x, target.y);
}
