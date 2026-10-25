import { test, expect, type Page } from "./fixtures";
import { randomUUID } from "node:crypto";
import type { Settings, Simulation, WorldFrame } from "../src/api/types";

async function api<T>(
  page: Page,
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const session = (await (await page.request.get("/api/v1/session")).json())
    .data;
  const response = await page.request.fetch("/api/v1" + path, {
    method,
    data: body,
    headers: {
      "X-CSRF-Token": session.csrf_token,
      "Idempotency-Key":
        (body as { request_id?: string } | undefined)?.request_id ??
        randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()).data;
}

test("paused steps visibly walk into a building and leave through its entrance", async ({
  page,
}, info) => {
  const { version, ...settings } = await api<Settings>(page, "/settings");
  await api(page, "/settings", "PUT", {
    expected_version: version,
    settings: { ...settings, view_mode: "3d", reduce_motion: false },
  });
  const city = await api<Simulation>(page, "/simulations", "POST", {
    config: {
      name: "Walking neighbors",
      seed: 73,
      population: 10,
      environment: { settlement: "suburb" },
    },
  });
  await expect
    .poll(
      async () =>
        (await api<Simulation>(page, `/simulations/${city.id}`)).status,
    )
    .toBe("paused");
  let frame = await api<WorldFrame>(page, `/simulations/${city.id}/state`);
  const agent = frame.agents[0];
  const building = [...frame.map.buildings].sort(
    (a, b) =>
      Math.hypot(
        a.entrance.x - agent.position.x,
        a.entrance.y - agent.position.y,
      ) -
      Math.hypot(
        b.entrance.x - agent.position.x,
        b.entrance.y - agent.position.y,
      ),
  )[0];
  const command = async (command: unknown) =>
    api(page, `/simulations/${city.id}/commands`, "POST", {
      request_id: randomUUID(),
      expected_control_version: (
        await api<Simulation>(page, `/simulations/${city.id}`)
      ).control_version,
      command,
    });
  await page.goto(`/simulations/${city.id}?qa=1`);
  await page
    .getByRole("button", { name: `Focus on ${agent.name}`, exact: true })
    .click();
  const label = page.locator(`[data-character-id="${agent.id}"]`);
  await expect(label).toBeVisible();
  await expect(label).toHaveAttribute("data-world-x");
  const move = (target: string | null, destination: unknown = null) =>
    command({
      type: "override_agent",
      agent_id: agent.id,
      metrics: {},
      goal: null,
      memory_text: null,
      intent: {
        action: "move",
        target_id: target,
        destination,
        parameters: { resource_kind: null, amount: null, message: null },
        motivation: "Visit a neighbor's building",
        emotion: "calm",
      },
    });
  await move(building.id);
  const observations = page.evaluate(async (id) => {
    const samples: string[] = [];
    const until = performance.now() + 5000;
    while (performance.now() < until) {
      await new Promise<void>((resolve) =>
        requestAnimationFrame(() => resolve()),
      );
      const el = document.querySelector<HTMLElement>(
        `[data-character-id="${id}"]`,
      );
      if (el?.dataset.worldX)
        samples.push(
          `${Number(el.dataset.worldX).toFixed(3)},${Number(el.dataset.worldY).toFixed(3)}`,
        );
    }
    return samples;
  }, agent.id);
  await command({ type: "step", count: 1 });
  // Software-rendered WebGL can paint only a few frames per second, so the
  // window spans the whole walk and checks for in-between positions.
  const samples = await observations;
  const [start, end] = [samples[0], samples.at(-1)];
  expect(start).not.toBe(end);
  expect(
    new Set(samples.filter((s) => s !== start && s !== end)).size,
  ).toBeGreaterThan(1);
  for (let i = 0; i < 12; i++) {
    frame = await api<WorldFrame>(page, `/simulations/${city.id}/state`);
    if (!frame.agents.find((a) => a.id === agent.id)!.path.length) break;
    await command({ type: "step", count: 1 });
  }
  await expect(
    page.getByRole("complementary", { name: "Character focus" }),
  ).toContainText(`Inside ${building.name}`);
  expect(
    frame.map.buildings.find((b) => b.id === building.id)!.occupancy,
  ).toBeGreaterThan(0);
  await page.screenshot({
    path: info.outputPath("inside-building.png"),
    fullPage: true,
  });
  await move(null, agent.position);
  for (let i = 0; i < 12; i++) {
    await command({ type: "step", count: 1 });
    frame = await api<WorldFrame>(page, `/simulations/${city.id}/state`);
    if (!frame.agents.find((a) => a.id === agent.id)!.path.length) break;
  }
  await expect(
    page.getByRole("complementary", { name: "Character focus" }),
  ).not.toContainText(`Inside ${building.name}`);
  await expect(
    page.getByRole("button", { name: "Visit building", exact: true }),
  ).toBeEnabled();
});
