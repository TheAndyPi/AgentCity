import { test, expect, type Page } from "./fixtures";
import { randomUUID } from "node:crypto";
import type { Settings, Simulation, WorldFrame } from "../src/api/types";

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
        (data as { request_id?: string } | undefined)?.request_id ??
        randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()).data;
}

test("Continue resumes a scenario and citizens stay active in the live map afterward", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const { version, ...settings } = await api<Settings>(page, "/settings");
  await api(page, "/settings", "PUT", {
    expected_version: version,
    settings: { ...settings, view_mode: "2d", reduce_motion: true },
  });
  const city = await api<Simulation>(page, "/simulations", "POST", {
    config: {
      name: "Scenario movement regression",
      seed: 42,
      population: 10,
      scenario_description: "An alien arrival during a festival for 2 ticks",
    },
  });
  const simulation = () => api<Simulation>(page, `/simulations/${city.id}`);
  const state = () => api<WorldFrame>(page, `/simulations/${city.id}/state`);
  const command = async (command: unknown) =>
    api(page, `/simulations/${city.id}/commands`, "POST", {
      request_id: randomUUID(),
      expected_control_version: (await simulation()).control_version,
      command,
    });
  await expect.poll(async () => (await simulation()).status).toBe("paused");
  await page.goto(`/simulations/${city.id}`);
  await page
    .getByRole("button", { name: "Confirm opening event", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Play simulation", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("Event outcome");
  const outcome = await state();
  expect(outcome.simulation.pause_reason).toBe("outcome");
  expect(outcome.events[0].status).toBe("resolved");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect
    .poll(async () => (await simulation()).tick)
    .toBeGreaterThan(outcome.ref.tick + 5);
  await page
    .getByRole("button", { name: "Pause simulation", exact: true })
    .click();
  await expect.poll(async () => (await simulation()).status).toBe("paused");
  // Go well beyond event resolution: the previous deadlock appeared only after
  // citizens finished their first visits and tried to share the same doorways.
  for (let i = 0; i < 6; i++) await command({ type: "step", count: 10 });
  const before = await state();
  const positions = new Map(before.agents.map((a) => [a.id, a.position]));
  const moved = new Set<string>();
  for (let i = 0; i < 4; i++) {
    await command({ type: "step", count: 10 });
    for (const agent of (await state()).agents) {
      const start = positions.get(agent.id)!;
      if (
        Math.hypot(start.x - agent.position.x, start.y - agent.position.y) > 1
      )
        moved.add(agent.id);
    }
  }
  expect(moved.size).toBe(10);
  const after = await state();
  expect(after.ref.tick).toBe(before.ref.tick + 40);
  expect(after.simulation.pending_outcome_event_ids).toEqual([]);
  await expect(page.locator(".connection")).toHaveText("LIVE");
  // Verify the actual rendered map follows committed coordinates over the
  // WebSocket; API movement alone would miss a disconnected rendering engine.
  for (const agent of after.agents) {
    const walker = page
      .locator("svg.world-2d")
      .getByRole("button", {
        name: `${agent.name}, ${agent.role}`,
        exact: true,
      })
      .locator("g")
      .first();
    await expect(walker).toHaveAttribute(
      "transform",
      `translate(${agent.position.x},${after.map.height_m - agent.position.y})`,
    );
  }
  await page.screenshot({
    path: info.outputPath("after-scenario-still-moving.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
