import { test, expect, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { defaultConfig } from "../src/api/defaults";
import type { Simulation, WorldFrame } from "../src/api/types";

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
      "Idempotency-Key": randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()).data;
}

test("a ten-person cast can be visited, invited into a readable chat, and inspected on mobile", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const city = await api<Simulation>(page, "/simulations", "POST", {
    config: {
      name: "A little neighborhood",
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
  const world = await api<WorldFrame>(page, `/simulations/${city.id}/state`);
  expect(world.map.buildings).toHaveLength(24);
  let pair = [world.agents[0], world.agents[1]];
  for (const a of world.agents)
    for (const b of world.agents)
      if (
        a.id !== b.id &&
        Math.hypot(a.position.x - b.position.x, a.position.y - b.position.y) <
          Math.hypot(
            pair[0].position.x - pair[1].position.x,
            pair[0].position.y - pair[1].position.y,
          )
      )
        pair = [a, b];
  const [a, b] = pair;
  await page.goto(`/simulations/${city.id}?qa=1`);
  await expect(
    page.getByRole("region", { name: "Your neighbors" }).getByRole("button"),
  ).toHaveCount(10);
  await expect(page.locator(".world-wrap canvas")).toBeVisible();
  await page
    .getByRole("button", { name: `Focus on ${a.name}`, exact: true })
    .click();
  const focus = page.getByRole("complementary", { name: "Character focus" });
  await expect(focus).toContainText(a.name);
  await expect(focus.getByRole("meter")).toHaveCount(4);
  await focus.getByLabel("Choose a neighbor to meet").selectOption(b.id);
  await focus
    .getByRole("button", { name: "Invite to chat", exact: true })
    .click();
  const conversation = page.getByRole("region", {
    name: "Close-up conversation",
  });
  await expect(conversation).toBeVisible();
  const pause = conversation.getByRole("button", {
    name: "Pause to read",
    exact: true,
  });
  await expect(pause).toBeEnabled();
  await pause.click();
  await expect(
    conversation.getByRole("button", { name: "Next moment" }),
  ).toBeEnabled();
  for (let i = 0; i < 7; i++) {
    const frame = await api<WorldFrame>(page, `/simulations/${city.id}/state`);
    const lines = frame.recent_dialogue.filter(
      (d) =>
        [d.speaker_id, ...d.recipient_ids].includes(a.id) &&
        [d.speaker_id, ...d.recipient_ids].includes(b.id),
    );
    if (lines.at(-1)?.end_conversation) break;
    await conversation.getByRole("button", { name: "Next moment" }).click();
    await expect
      .poll(
        async () =>
          (await api<Simulation>(page, `/simulations/${city.id}`)).tick,
      )
      .toBeGreaterThan(frame.ref.tick);
    await expect(
      conversation.getByRole("button", { name: "Next moment" }),
    ).toBeEnabled();
  }
  await expect(conversation.locator("article")).toHaveCount(4);
  await expect(conversation).toContainText("Until next time.");
  const result = await api<WorldFrame>(page, `/simulations/${city.id}/state`);
  const lines = result.recent_dialogue.filter(
    (d) =>
      [d.speaker_id, ...d.recipient_ids].includes(a.id) &&
      [d.speaker_id, ...d.recipient_ids].includes(b.id),
  );
  expect(new Set(lines.map((d) => d.tick)).size).toBe(4);
  const position = (id: string) =>
    result.agents.find((agent) => agent.id === id)!.position;
  expect(
    Math.hypot(
      position(a.id).x - position(b.id).x,
      position(a.id).y - position(b.id).y,
    ),
  ).toBeLessThanOrEqual(3);
  await expect(page.locator("[data-qa-fps]")).toContainText("FPS");
  await page.screenshot({
    path: info.outputPath("ten-neighbors-closeup-desktop.png"),
    fullPage: true,
  });
  const bubble = page.locator(`[data-speaker-id="${b.id}"]`);
  const closeWidth = (await bubble.boundingBox())!.width;
  for (let i = 0; i < 6; i++)
    await page.getByRole("button", { name: "Zoom out", exact: true }).click();
  await expect
    .poll(async () => (await bubble.boundingBox())!.width)
    .toBeLessThan(closeWidth * 0.8);
  await page.screenshot({
    path: info.outputPath("zoomed-out-dialogue.png"),
    fullPage: true,
  });
  for (let i = 0; i < 6; i++)
    await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(conversation).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Your neighbors" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("ten-neighbors-closeup-mobile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Close character focus" }).click();
  await expect(conversation).not.toBeVisible();
  // Wide view keeps both sides of the exchange visible without a selection.
  await expect(page.locator(`[data-speaker-id="${a.id}"]`)).toBeVisible();
  await expect(page.locator(`[data-speaker-id="${b.id}"]`)).toBeVisible();
  await expect
    .poll(async () => {
      const left = await page
        .locator(`[data-speaker-id="${a.id}"]`)
        .boundingBox();
      const right = await page
        .locator(`[data-speaker-id="${b.id}"]`)
        .boundingBox();
      return (
        !!left &&
        !!right &&
        (left.x + left.width <= right.x ||
          right.x + right.width <= left.x ||
          left.y + left.height <= right.y ||
          right.y + right.height <= left.y)
      );
    })
    .toBe(true);
  await page.screenshot({
    path: info.outputPath("wide-view-bubbles.png"),
    fullPage: true,
  });
  await expect(
    page.getByRole("region", { name: "Your neighbors" }).getByRole("button"),
  ).toHaveCount(10);
  expect(errors).toEqual([]);
});

test("new neighborhoods keep a fixed cast of ten even when an older draft asked for more", async ({
  page,
}) => {
  await page.addInitScript(
    (config) =>
      localStorage.setItem(
        "agentcity-setup-draft",
        JSON.stringify({ ...config, population: 80 }),
      ),
    defaultConfig,
  );
  await page.goto("/simulations/new");
  await expect(page.getByLabel("Population", { exact: true })).toHaveValue(
    "10",
  );
  await expect(page.getByLabel("Population", { exact: true })).toHaveAttribute(
    "readonly",
    "",
  );
  await expect(
    page.getByRole("heading", {
      name: "Ten people. A world of little moments.",
    }),
  ).toBeVisible();
});
