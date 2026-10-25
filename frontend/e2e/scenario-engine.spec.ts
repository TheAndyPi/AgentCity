import { randomUUID } from "node:crypto";
import { test, expect } from "./fixtures";

test("a catalog dinosaur event can be composed, committed and shown in the city", async ({
  page,
}) => {
  await page.goto("/");
  const session = await (await page.request.get("/api/v1/session")).json();
  const created = await page.request.post("/api/v1/simulations", {
    headers: {
      "X-CSRF-Token": session.data.csrf_token,
      "Idempotency-Key": randomUUID(),
    },
    data: {
      config: {
        name: "Dinosaur catalog integration",
        seed: 42,
        population: 10,
      },
    },
  });
  expect(created.status()).toBe(202);
  const id = (await created.json()).data.id as string;
  const read = async (path: string) =>
    (await (await page.request.get(`/api/v1${path}`)).json()).data;
  await expect
    .poll(async () => (await read(`/simulations/${id}`)).status)
    .toBe("paused");
  await page.goto(`/simulations/${id}`);
  await page
    .getByRole("button", { name: "Introduce an event", exact: true })
    .click();
  await page
    .getByLabel("Describe your event")
    .fill("2 red dinosaurs appear for 4 ticks");
  await page
    .getByRole("button", { name: "Preview event", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Compose manually", exact: true })
    .click();
  await page.getByLabel("Measurement window (ticks)").fill("4");
  await page.getByLabel("Change to add").selectOption("catalog_event");
  await page.getByRole("button", { name: "Add change", exact: true }).click();
  await page.getByLabel(/^Recipe/).selectOption("dinosaurs");
  await page.getByLabel(/^Region/).selectOption("citywide");
  await page.getByLabel(/^Count/).fill("2");
  await page.getByLabel("Color", { exact: true }).fill("#db7567");
  await page
    .getByRole("button", { name: "Review changes", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText(
    "dinosaurs scenery and catalog effects",
  );
  await page
    .getByRole("button", { name: "Confirm and Start", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Step one tick", exact: true })
    .click();
  await expect
    .poll(async () => (await read(`/simulations/${id}`)).tick)
    .toBe(1);
  const events = (await read(`/simulations/${id}/state`)).events;
  expect(events).toHaveLength(1);
  expect(events[0].scene).toHaveLength(2);
  expect(
    events[0].scene.every(
      (prop: { model: string }) => prop.model === "dinosaur",
    ),
  ).toBe(true);
});

test("event generation failures explain the cause and can be retried", async ({
  page,
}) => {
  await page.goto("/");
  const session = await (await page.request.get("/api/v1/session")).json();
  const headers = {
    "X-CSRF-Token": session.data.csrf_token,
    "Idempotency-Key": randomUUID(),
  };
  const created = await page.request.post("/api/v1/simulations", {
    headers,
    data: {
      config: { name: "Retry event integration", seed: 42, population: 10 },
    },
  });
  expect(created.status()).toBe(202);
  const id = (await created.json()).data.id as string;
  await expect
    .poll(async () => {
      const response = await page.request.get(`/api/v1/simulations/${id}`);
      return (await response.json()).data.status;
    })
    .toBe("paused");
  const validated = await page.request.post(
    `/api/v1/integrations/scenarios/simulations/${id}/plans/validate`,
    {
      headers: { ...headers, "Idempotency-Key": randomUUID() },
      data: {
        plan: {
          title: "New transit fare",
          category: "policy",
          description: "Set transit fares to two credits.",
          public_description: "Transit fares are now two credits.",
          duration: "temporary",
          measurement_ticks: 4,
          affected_systems: ["transportation"],
          metrics: ["transit_usage"],
          source: "gemini",
          operations: [
            {
              type: "modify_policy",
              id: "fare",
              rationale: "Requested transit price",
              target: "transportation.transit_fare",
              operation: "set",
              value: 2,
            },
          ],
        },
      },
    },
  );
  expect(validated.status()).toBe(200);
  const ready = await validated.json();
  expect(ready.data.status).toBe("ready");
  const calls: unknown[] = [];
  await page.route(
    `**/api/v1/integrations/scenarios/simulations/${id}/plans`,
    async (route) => {
      calls.push(route.request().postDataJSON());
      await route.fulfill({
        json:
          calls.length === 1
            ? {
                schema_version: "1.0.0",
                request_id: randomUUID(),
                data: {
                  status: "unavailable",
                  plan: null,
                  summary: null,
                  warnings: [],
                  unsupported: [],
                  errors: [
                    "The remaining Gemini token allowance is too small to plan this event.",
                  ],
                  clarification: "",
                  attempts: 1,
                },
              }
            : ready,
      });
    },
  );
  await page.goto(`/simulations/${id}`);
  await page
    .getByRole("button", { name: "Introduce an event", exact: true })
    .click();
  await page
    .getByLabel("Describe your event")
    .fill("Set transit fares to two credits.");
  await page
    .getByRole("button", { name: "Preview event", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Event generation is unavailable");
  await expect(dialog).toContainText("remaining Gemini token allowance");
  await expect(dialog).not.toContainText(
    "This plan needs changes before it can run",
  );
  await page.getByRole("button", { name: "Retry event", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Confirm and Start", exact: true }),
  ).toBeVisible();
  expect(calls).toHaveLength(2);
  expect(calls[0]).toEqual(calls[1]);
});

test("manual scenario plan validates, commits, changes policy and restores its temporary effect", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  const session = await (await page.request.get("/api/v1/session")).json();
  const created = await page.request.post("/api/v1/simulations", {
    headers: {
      "X-CSRF-Token": session.data.csrf_token,
      "Idempotency-Key": randomUUID(),
    },
    data: {
      config: { name: "Manual policy integration", seed: 42, population: 10 },
    },
  });
  expect(created.status()).toBe(202);
  const id = (await created.json()).data.id as string;
  const read = async (path: string) =>
    (await (await page.request.get(`/api/v1${path}`)).json()).data;
  await expect
    .poll(async () => (await read(`/simulations/${id}`)).status)
    .toBe("paused");
  await page.goto(`/simulations/${id}`);
  await expect(page.locator(".connection")).toHaveText("LIVE");
  await page
    .getByRole("button", { name: "Introduce an event", exact: true })
    .click();
  await page
    .getByLabel("Describe your event")
    .fill("Temporarily change transit fares to three credits.");
  await page
    .getByRole("button", { name: "Preview event", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Compose manually", exact: true })
    .click();
  await page.getByLabel("Measurement window (ticks)").fill("4");
  await page.getByLabel("Change to add").selectOption("modify_policy");
  await page.getByRole("button", { name: "Add change", exact: true }).click();
  await page.getByLabel(/^Target/).selectOption("transportation.transit_fare");
  await page.getByLabel(/^Operation/).selectOption("set");
  await page.getByLabel(/^Value/).fill("3");
  await page
    .getByRole("button", { name: "Review changes", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Confirm and Start", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const statePath = `/integrations/scenarios/simulations/${id}/state`;
  const baseline = (await read(statePath)).policy.transportation.transit_fare;
  for (let n = 1; n <= 5; n++) {
    await page
      .getByRole("button", { name: "Step one tick", exact: true })
      .click();
    await expect
      .poll(async () => (await read(`/simulations/${id}`)).tick)
      .toBe(n);
    if (n === 1)
      expect((await read(statePath)).policy.transportation.transit_fare).toBe(
        3,
      );
  }
  await expect(page.getByRole("dialog")).toContainText("Event outcome");
  const systems = await read(statePath);
  expect(systems.policy.transportation.transit_fare).toBe(baseline);
  expect(systems.plans[0].status).toBe("resolved");
  expect(errors).toEqual([]);
});
