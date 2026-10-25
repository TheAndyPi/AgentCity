import { test, expect, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import type { Simulation, Settings } from "../src/api/types";
import type { DisasterState } from "../src/disasters/client";
test.beforeAll(() => {
  mkdirSync("artifacts/disasters", { recursive: true });
});

async function api<T>(
  page: Page,
  path: string,
  method = "GET",
  data?: unknown,
): Promise<T> {
  const csrf = (await (await page.request.get("/api/v1/session")).json()).data
    .csrf_token;
  const response = await page.request.fetch("/api/v1" + path, {
    method,
    data,
    headers: { "X-CSRF-Token": csrf, "Idempotency-Key": randomUUID() },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()).data;
}
async function setup(page: Page) {
  const { version, ...settings } = await api<Settings>(page, "/settings");
  await api(page, "/settings", "PUT", {
    expected_version: version,
    settings: { ...settings, view_mode: "2d", reduce_motion: true },
  });
  const s = await api<Simulation>(page, "/simulations", "POST", {
    config: { name: "Disaster acceptance", seed: 42, population: 10 },
  });
  await expect
    .poll(
      async () => (await api<Simulation>(page, `/simulations/${s.id}`)).status,
    )
    .toBe("paused");
  await page.goto(`/simulations/${s.id}`);
  await expect(
    page.getByRole("button", { name: "Introduce an event", exact: true }),
  ).toBeVisible();
  return s.id;
}
async function introduce(page: Page, kind: string) {
  await page
    .getByRole("button", { name: "Introduce an event", exact: true })
    .click();
  await expect(page.getByLabel("Disaster type")).toBeVisible();
  await page.getByLabel("Disaster type").selectOption(kind);
}
test("DS controls are independent and damage survives outcome and reload", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const sid = await setup(page);
  await introduce(page, "earthquake");
  const magnitude = page.getByRole("spinbutton", {
    name: "Moment magnitude (Mw) value",
    exact: true,
  });
  const radius = page.getByRole("spinbutton", {
    name: "Footprint radius (m) value",
    exact: true,
  });
  await magnitude.fill("9");
  await radius.fill("50");
  await expect(magnitude).toHaveValue("9");
  await page
    .getByRole("spinbutton", { name: "Duration (ticks) value", exact: true })
    .fill("2");
  await page
    .getByRole("button", { name: "Preview event", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Confirm event", exact: true }),
  ).toBeEnabled();
  await expect(page.getByRole("dialog")).toContainText("9 Mw");
  await radius.fill("48");
  await expect(
    page.getByRole("button", { name: "Confirm event", exact: true }),
  ).toHaveCount(0);
  await expect(magnitude).toHaveValue("9");
  await page
    .getByRole("button", { name: "Preview event", exact: true })
    .click();
  await page.getByRole("dialog").evaluate((node) => {
    node.scrollTop = 0;
  });
  await page.screenshot({
    path: "artifacts/disasters/controls.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Confirm event", exact: true })
    .click();
  for (let i = 0; i < 3; i++) {
    await page
      .getByRole("button", { name: "Step one tick", exact: true })
      .click();
    await expect
      .poll(
        async () => (await api<Simulation>(page, `/simulations/${sid}`)).tick,
      )
      .toBe(i + 1);
  }
  await expect(page.getByRole("dialog")).toContainText("Event outcome");
  const before = await api<DisasterState>(
    page,
    `/integrations/disasters/v2/simulations/${sid}/state`,
  );
  expect(before.damage.length).toBeGreaterThan(0);
  expect(
    Object.values(before.conditions).some((c) => c.integrity < 100),
  ).toBeTruthy();
  await page.getByRole("button", { name: /Continue/ }).click();
  await page.locator(".disaster-panel summary").click();
  await expect(page.locator(".disaster-panel")).toContainText("Integrity");
  await page.reload();
  const after = await api<DisasterState>(
    page,
    `/integrations/disasters/v2/simulations/${sid}/state`,
  );
  expect(after.conditions).toEqual(before.conditions);
  expect(after.damage).toEqual(before.damage);
  await expect(page.locator(".disaster-panel summary")).toContainText(
    "damaged buildings",
  );
  await expect(
    page.locator(".world-2d text").filter({ hasText: "×" }).first(),
  ).toBeVisible();
  await page.screenshot({
    path: "artifacts/disasters/aftermath.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
test("DA decoded effects and music stop at cancellation; reload stays silent", async ({
  page,
}, info) => {
  await page.addInitScript(() => {
    const tracked = new Set<HTMLMediaElement>();
    const original = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () {
      tracked.add(this);
      return original.call(this);
    };
    Object.defineProperty(window, "__disasterMedia", {
      value: () =>
        [...tracked].map((p) => ({
          bus: p.dataset.audioBus,
          src: p.currentSrc || p.src,
          time: p.currentTime,
          paused: p.paused,
          ready: p.readyState,
        })),
    });
  });
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await setup(page);
  await introduce(page, "fire");
  await page
    .getByRole("spinbutton", {
      name: "Gameplay heat (/100) value",
      exact: true,
    })
    .fill("100");
  await page
    .getByRole("spinbutton", {
      name: "Footprint radius (m) value",
      exact: true,
    })
    .fill("45");
  await page
    .getByRole("spinbutton", { name: "Duration (ticks) value", exact: true })
    .fill("80");
  await page
    .getByRole("button", { name: "Preview event", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Confirm event", exact: true })
    .click();
  await page.getByRole("button", { name: "Enable sound", exact: true }).click();
  await page
    .getByRole("button", { name: "Play simulation", exact: true })
    .click();
  const media = () =>
    page.evaluate(() =>
      (
        window as unknown as {
          __disasterMedia: () => Array<{
            bus: string;
            src: string;
            time: number;
            paused: boolean;
            ready: number;
          }>;
        }
      ).__disasterMedia(),
    );
  try {
    await expect
      .poll(
        async () =>
          (await media()).filter(
            (p) =>
              p.bus === "disaster" && !p.paused && p.ready >= 2 && p.time > 0,
          ).length,
        { timeout: 20000 },
      )
      .toBeGreaterThanOrEqual(2);
  } catch (error) {
    await info.attach("audio-diagnostics", {
      body: JSON.stringify({
        media: await media(),
        ui: await page.locator(".live-voices").innerText(),
        enabled: await page
          .locator(".live-voices")
          .getAttribute("data-sound-enabled"),
        events: await page
          .locator(".live-voices")
          .getAttribute("data-sound-events"),
      }),
      contentType: "application/json",
    });
    throw error;
  }
  expect(
    (await media()).filter((p) => p.bus === "disaster" && !p.paused).length,
  ).toBeLessThanOrEqual(3);
  await page.screenshot({
    path: "artifacts/disasters/audio.png",
    fullPage: true,
  });
  await page.locator(".disaster-panel summary").click();
  await page
    .getByRole("button", { name: "Stop disaster", exact: true })
    .click();
  await expect
    .poll(
      async () =>
        (await media()).filter((p) => p.bus === "disaster" && !p.paused).length,
    )
    .toBe(0);
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Enable sound", exact: true }),
  ).toBeVisible();
  expect((await media()).filter((p) => !p.paused)).toHaveLength(0);
  expect(errors).toEqual([]);
});

test("DS-02 editing an in-flight preview stays responsive and ignores the old response", async ({
  page,
}) => {
  const sid = await setup(page);
  await introduce(page, "flood");
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let requests = 0;
  await page.route(
    "**/integrations/disasters/v2/simulations/*/previews",
    async (route) => {
      requests++;
      const response = await route.fetch();
      if (requests === 1) await gate;
      try {
        await route.fulfill({ response });
      } catch {
        /* superseded browser request was aborted */
      }
    },
  );
  await page
    .getByRole("button", { name: "Preview event", exact: true })
    .click();
  await expect.poll(() => requests).toBe(1);
  await page
    .getByRole("spinbutton", { name: "Water depth (m) value", exact: true })
    .fill("2");
  await expect(
    page.getByRole("button", { name: "Preview event", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Preview event", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Confirm event", exact: true }),
  ).toBeEnabled();
  release();
  await expect(page.getByRole("dialog")).toContainText("Flood · 2 m");
  await page
    .getByRole("button", { name: "Confirm event", exact: true })
    .click();
  await expect
    .poll(
      async () =>
        (
          await api<DisasterState>(
            page,
            `/integrations/disasters/v2/simulations/${sid}/state`,
          )
        ).events.at(-1)?.parameters.intensity,
    )
    .toBe(2);
});
