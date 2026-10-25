import { randomUUID } from "node:crypto";
import { test, expect } from "./fixtures";

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
  await page
    .getByLabel(/^Target/)
    .selectOption("transportation.transit_fare");
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
