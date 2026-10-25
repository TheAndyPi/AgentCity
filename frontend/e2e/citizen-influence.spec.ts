import { test, expect, type Page } from "./fixtures";
import { randomUUID } from "node:crypto";
import { select3DCitizen } from "./world-selection";
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

test("citizens can become lovers and speak an exact user line on mobile", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const { version, ...settings } = await api<Settings>(page, "/settings");
  await api(page, "/settings", "PUT", {
    expected_version: version,
    settings: { ...settings, view_mode: "3d", reduce_motion: false },
  });
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
  let world = await api<WorldFrame>(page, `/simulations/${city.id}/state`);
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
  // Bring the neighbors together using real, speed-limited movement. Their
  // autonomous errands may now use different routes around occupied buildings;
  // this conversation UI test should start with a reachable nearby invitation.
  const middle = {
    x: (pair[0].position.x + pair[1].position.x) / 2,
    y: (pair[0].position.y + pair[1].position.y) / 2,
  };
  const length = Math.hypot(
    pair[0].position.x - pair[1].position.x,
    pair[0].position.y - pair[1].position.y,
  );
  const command = async (command: unknown) =>
    api(page, `/simulations/${city.id}/commands`, "POST", {
      request_id: randomUUID(),
      expected_control_version: (
        await api<Simulation>(page, `/simulations/${city.id}`)
      ).control_version,
      command,
    });
  for (const citizen of pair) {
    await command({
      type: "override_agent",
      agent_id: citizen.id,
      metrics: {},
      goal: null,
      memory_text: null,
      intent: {
        action: "move",
        target_id: null,
        destination: {
          x: middle.x + ((citizen.position.x - middle.x) / length) * 1.1,
          y: middle.y + ((citizen.position.y - middle.y) / length) * 1.1,
        },
        parameters: { resource_kind: null, amount: null, message: null },
        motivation: "Meet my neighbor outside",
        emotion: "calm",
      },
    });
  }
  for (let step = 0; step < 8; step++) {
    await command({ type: "step", count: 1 });
    world = await api<WorldFrame>(page, `/simulations/${city.id}/state`);
    const [left, right] = pair.map(
      (citizen) => world.agents.find((a) => a.id === citizen.id)!,
    );
    if (
      Math.hypot(
        left.position.x - right.position.x,
        left.position.y - right.position.y,
      ) <= 3
    )
      break;
  }
  const [a, b] = pair.map(
    (citizen) => world.agents.find((agent) => agent.id === citizen.id)!,
  );
  expect(
    Math.hypot(a.position.x - b.position.x, a.position.y - b.position.y),
  ).toBeLessThanOrEqual(3);
  await page.goto(`/simulations/${city.id}?qa=1`);
  const map = page.locator(".world-wrap canvas");
  await expect(map).toBeVisible();
  // Current dev selects citizens on the map; the former neighbor strip is gone.
  await select3DCitizen(page, a.position);
  const focus = page.getByRole("complementary", { name: "Character focus" });
  await expect(
    page.getByRole("heading", { name: a.name, exact: true }),
  ).toBeVisible();
  await expect(focus.getByRole("meter")).toHaveCount(5);
  await expect(
    focus.getByLabel("Choose a neighbor to meet").locator("option"),
  ).toHaveCount(9);
  expect(
    (
      await focus
        .getByLabel("Choose a neighbor to meet")
        .locator("option")
        .evaluateAll((options) =>
          options.map((option) => (option as HTMLOptionElement).value),
        )
    ).sort(),
  ).toEqual(
    world.agents
      .filter((agent) => agent.id !== a.id)
      .map((agent) => agent.id)
      .sort(),
  );
  await focus.getByLabel("Choose a neighbor to meet").selectOption(b.id);
  const influence = focus.getByRole("region", {
    name: "Influence",
    exact: true,
  });
  await expect(
    influence.getByRole("button", { name: "Say this", exact: true }),
  ).toBeDisabled();
  await influence.getByLabel("Relationship preset").selectOption("lovers");
  await influence.getByRole("button", { name: "Apply relationship" }).click();
  await expect(influence.getByRole("status")).toContainText("are now lovers");
  const relation = await api<{
    relationships: {
      items: { to_agent_id: string; kind: string; affection: number }[];
    };
  }>(page, `/simulations/${city.id}/agents/${a.id}`);
  expect(
    relation.relationships.items.find((tie) => tie.to_agent_id === b.id),
  ).toMatchObject({ kind: "romantic", affection: 95 });
  expect((await api<Simulation>(page, `/simulations/${city.id}`)).status).toBe(
    "paused",
  );
  const words = "  I saved this neon-lit moment for you!  ";
  await influence.getByLabel("Exact line to say").fill("   ");
  await expect(
    influence.getByRole("button", { name: "Say this", exact: true }),
  ).toBeDisabled();
  await expect(influence.getByLabel("Exact line to say")).toHaveAttribute(
    "maxlength",
    "2000",
  );
  await influence.getByLabel("Exact line to say").fill(words);
  await page.setViewportSize({ width: 390, height: 844 });
  await influence.getByLabel("Exact line to say").scrollIntoViewIfNeeded();
  expect((await influence.boundingBox())!.width).toBeLessThanOrEqual(390);
  await page.screenshot({
    path: info.outputPath("citizen-influence-mobile.png"),
  });
  await page.route(
    `**/api/v1/simulations/${city.id}/commands`,
    async (route) => {
      const request = route.request().postDataJSON();
      if (request?.command?.type === "override_agent") {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            schema_version: "1.0.0",
            request_id: randomUUID(),
            error: {
              code: "CONTROL_CONFLICT",
              message: "The city changed. Try again.",
              retryable: false,
              details: [],
            },
          }),
        });
      } else await route.continue();
    },
  );
  await influence
    .getByRole("button", { name: "Say this", exact: true })
    .click();
  await expect(focus.getByRole("alert")).toContainText(
    "The city changed. Try again.",
  );
  await expect(influence.getByLabel("Exact line to say")).toHaveValue(words);
  await page.unroute(`**/api/v1/simulations/${city.id}/commands`);
  await influence
    .getByRole("button", { name: "Say this", exact: true })
    .click();
  await expect(influence.getByRole("status")).toContainText("Requested");
  await expect(influence.getByLabel("Exact line to say")).toHaveValue("");
  const conversation = page.getByRole("region", {
    name: "Close-up conversation",
  });
  await expect(conversation).toBeVisible();
  await expect(
    conversation.locator("article p").filter({ hasText: words.trim() }),
  ).toBeVisible();
  await expect(influence).toContainText(`${a.name} → ${b.name}`);
  expect(errors).toEqual([]);
});
