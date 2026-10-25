import { randomUUID } from "node:crypto";
import { test, expect, type Page } from "@playwright/test";
import type { Simulation, WorldFrame } from "../src/api/types";

async function api(
  page: Page,
  path: string,
  body?: unknown,
  method = body ? "POST" : "GET",
) {
  const session = (await (await page.request.get("/api/v1/session")).json())
    .data;
  const response = await page.request.fetch("/api/v1" + path, {
    method,
    data: body,
    headers: {
      "X-CSRF-Token": session.csrf_token,
      "Idempotency-Key": randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

for (const mode of ["2d", "3d"] as const) {
  test(`${mode} follows the calendar through day, dusk, night, and dawn`, async ({
    page,
  }, info) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const { version, ...settings } = (await api(page, "/settings")).data;
    await api(
      page,
      "/settings",
      {
        expected_version: version,
        settings: { ...settings, view_mode: mode, reduce_motion: true },
      },
      "PUT",
    );
    const city: Simulation = (
      await api(page, "/simulations", {
        config: { name: "Daily life acceptance", seed: 42, population: 10 },
      })
    ).data;
    await expect
      .poll(
        async () => (await api(page, `/simulations/${city.id}`)).data.status,
      )
      .toBe("paused");
    for (const [hour, phase, steps] of [
      [12, "Day", 1],
      [20, "Dusk", 1],
      [23, "Night", 30],
      [30, "Dawn", 1],
    ] as const) {
      const setup = await api(page, `/integrations/calendar-test/${city.id}`, {
        hour,
        steps,
        curfew: phase === "Night",
      });
      await page.goto(`/simulations/${city.id}`);
      await expect(page.locator(".sim-clock")).toContainText(phase);
      if (mode === "2d")
        await expect(page.locator(".world-2d")).toHaveAttribute(
          "data-day-phase",
          phase,
        );
      else await expect(page.locator(".world-wrap canvas")).toBeVisible();
      const state: WorldFrame = (
        await api(page, `/simulations/${city.id}/state`)
      ).data;
      expect(state.simulation.calendar_time_seconds).toBe(
        setup.calendar_time_seconds,
      );
      if (phase === "Night") {
        expect(
          state.agents.filter((agent) => agent.routine_state === "sleeping")
            .length,
        ).toBeGreaterThanOrEqual(8);
        await expect(page.locator(".sim-clock")).toContainText("Curfew active");
      }
      if (phase === "Dawn")
        expect(
          state.agents.every((agent) => agent.routine_state !== "sleeping"),
        ).toBe(true);
      await page.screenshot({
        path: info.outputPath(`${mode}-${phase.toLowerCase()}.png`),
      });
    }
    expect(errors).toEqual([]);
  });
}
