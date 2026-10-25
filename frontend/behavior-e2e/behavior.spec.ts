import { test, expect, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import type { Simulation, WorldFrame } from "../src/api/types";
import { behaviorResponse } from "../src/behavior/schema";

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
      "Idempotency-Key":
        (body as { request_id?: string })?.request_id ?? randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}
async function setup(page: Page, mode: string) {
  const { version, ...settings } = (await api(page, "/settings")).data;
  await api(
    page,
    "/settings",
    { expected_version: version, settings: { ...settings, view_mode: "2d" } },
    "PUT",
  );
  const city: Simulation = (
    await api(page, "/simulations", {
      config: { name: "Behavior acceptance", seed: 42, population: 10 },
    })
  ).data;
  await expect
    .poll(async () => (await api(page, `/simulations/${city.id}`)).data.status)
    .toBe("paused");
  const ids = await api(page, `/integrations/behavior-test/${city.id}`, {
    mode,
  });
  return { sid: city.id, ...ids } as {
    sid: string;
    helper: string;
    patient: string;
  };
}
async function focus(page: Page, sid: string, aid: string) {
  await page.goto(`/simulations/${sid}?qa=1`);
  const frame: WorldFrame = (await api(page, `/simulations/${sid}/state`)).data;
  const selected = frame.agents.find((a) => a.id === aid)!;
  const target = page.locator(
    `.world-2d [role="button"][aria-label="${selected.name}, ${selected.role}"]`,
  );
  await target.focus();
  await target.press("Enter");
  const card = page.getByRole("complementary", { name: "Character focus" });
  await expect(
    card.getByRole("meter", { name: "Mental", exact: true }),
  ).toBeVisible();
  return card;
}
async function step(page: Page, sid: string, count = 1) {
  const simulation: Simulation = (await api(page, `/simulations/${sid}`)).data;
  const id = randomUUID();
  await api(page, `/simulations/${sid}/commands`, {
    request_id: id,
    expected_control_version: simulation.control_version,
    command: { type: "step", count },
  });
}

test("AB-17 faint -> physical rescue -> hospital -> recovery in the existing UI", async ({
  page,
}, info) => {
  const { sid, patient } = await setup(page, "faint");
  let card = await focus(page, sid, patient);
  await expect(card.getByLabel("Survival and care")).toContainText(
    "UNCONSCIOUS",
  );
  await expect(card.getByRole("button", { name: "Take a break" })).toHaveCount(
    0,
  );
  const start = (await api(page, `/simulations/${sid}/state`)).data.agents.find(
    (a: { id: string }) => a.id === patient,
  ).position;
  let hospitalized = false;
  for (let i = 0; i < 40; i++) {
    await step(page, sid);
    const snapshot = behaviorResponse.parse(
      await api(page, `/integrations/behavior/v2/simulations/${sid}`),
    ).data;
    if (snapshot.citizens[patient].care === "hospital" && !hospitalized) {
      hospitalized = true;
      card = await focus(page, sid, patient);
      await expect(card.getByLabel("Survival and care")).toContainText(
        /HOSPITALIZED|UNCONSCIOUS/,
      );
    }
    if (snapshot.analytics.counters.hospital_release) break;
  }
  expect(hospitalized).toBe(true);
  const result = behaviorResponse.parse(
    await api(page, `/integrations/behavior/v2/simulations/${sid}`),
  ).data;
  expect(result.analytics.counters.admission).toBe(1);
  expect(result.analytics.counters.hospital_release).toBe(1);
  expect(result.citizens[patient].life).toBe("alive");
  const end = (await api(page, `/simulations/${sid}/state`)).data.agents.find(
    (a: { id: string }) => a.id === patient,
  ).position;
  expect(end).not.toEqual(start);
  card = await focus(page, sid, patient);
  await expect(card.getByLabel("Survival and care")).toContainText("ALIVE");
  await page.screenshot({ path: info.outputPath("recovery.png") });
});

test("AB-17 fatal fullness shows exact cause and disables impossible commands", async ({
  page,
}) => {
  const { sid, patient } = await setup(page, "fatal");
  const card = await focus(page, sid, patient);
  await expect(card.getByLabel("Survival and care")).toContainText("DEAD");
  await expect(card.getByLabel("Survival and care")).toContainText("fullness");
  await expect(card.getByRole("button", { name: "Have a snack" })).toHaveCount(
    0,
  );
});

test("AB-17 two seeded crisis modes and public class encounter are visible", async ({
  page,
}) => {
  const crisis = await setup(page, "crisis");
  let card = await focus(page, crisis.sid, crisis.helper);
  await expect(card.getByLabel("Survival and care")).toContainText(
    "WITHDRAWAL",
  );
  card = await focus(page, crisis.sid, crisis.patient);
  await expect(card.getByLabel("Survival and care")).toContainText("SUPPORT");
  await step(page, crisis.sid);
  const classes = await setup(page, "classes");
  card = await focus(page, classes.sid, classes.helper);
  await expect(card.getByLabel("Survival and care")).toContainText(
    "Rich resource class",
  );
  await expect(card.getByLabel("Behavior evidence")).toContainText(
    "Discrimination",
  );
});

test("v2 attack evidence opens from historical citizen memories", async ({
  page,
}) => {
  const { sid, helper } = await setup(page, "attack");
  const card = await focus(page, sid, helper);
  await card
    .getByRole("button", { name: "Their story & relationships" })
    .click();
  const inspector = page.getByRole("complementary", { name: "A closer look" });
  await inspector.getByRole("tab", { name: "Memories", exact: true }).click();
  await inspector
    .getByRole("button", { name: "Decision evidence" })
    .first()
    .click();
  const proof = page.getByLabel("Behavior action evidence");
  await expect(proof).toContainText("Attack");
  await expect(proof).toContainText("Accepted");
  await expect(proof).toContainText("Health: -1.00");
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("survival stats stay visible while the next live revision loads", async ({
  page,
}) => {
  const { sid, helper } = await setup(page, "classes");
  const card = await focus(page, sid, helper);
  const survival = card.getByLabel("Survival and care");
  await expect(survival).toContainText("ALIVE");
  await step(page, sid);
  await expect(survival).toContainText("Daily");
  const beforeRefresh = (await survival.textContent())!;
  let release!: () => void;
  let requested!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const pending = new Promise<void>((resolve) => {
    requested = resolve;
  });
  await page.route(
    `**/integrations/behavior/v2/simulations/${sid}?*`,
    async (route) => {
      requested();
      await gate;
      await route.continue();
    },
  );
  try {
    await step(page, sid);
    await pending;
    await expect(survival).toBeVisible();
    await expect(survival).toHaveText(beforeRefresh);
    await expect(survival).toContainText("ALIVE");
    await expect(survival).toContainText("Rich resource class");
  } finally {
    release();
  }
  await expect(card.getByRole("button", { name: "Take a break" })).toHaveCount(
    0,
  );
  await expect(card.getByRole("button", { name: "Have a snack" })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: "World overlays", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Simulation overview", exact: true })
    .click();
  await expect(
    page.getByRole("complementary", { name: "The bigger picture" }),
  ).toBeVisible();
});
