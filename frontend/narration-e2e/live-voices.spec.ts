import { test, expect, type Page, type WebSocketRoute } from "@playwright/test";
import { randomUUID, createHash } from "node:crypto";
import { writeFileSync } from "node:fs";
import type {
  Dialogue,
  Settings,
  Simulation,
  WorldFrame,
} from "../src/api/types";

const fake = "http://127.0.0.1:10830/__fake-elevenlabs";
test.beforeEach(async ({ request }) => {
  await request.post(`${fake}/reset`);
});
test.afterEach(async ({ request }) => {
  await request.post(`${fake}/release`);
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
    headers: {
      "X-CSRF-Token": csrf,
      "Idempotency-Key":
        (data as { request_id?: string })?.request_id ?? randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()).data;
}
async function prepare(page: Page) {
  const { version, ...settings } = await api<Settings>(page, "/settings");
  await api(page, "/settings", "PUT", {
    expected_version: version,
    settings: { ...settings, view_mode: "2d", reduce_motion: true },
  });
  const city = await api<Simulation>(page, "/simulations", "POST", {
    config: { name: "Live voices", seed: 79, population: 10 },
  });
  await expect
    .poll(
      async () =>
        (await api<Simulation>(page, `/simulations/${city.id}`)).status,
    )
    .toBe("paused");
  const world = await api<WorldFrame>(page, `/simulations/${city.id}/state`);
  const commit = async (
    participants: string[],
    interaction: string,
    count = 1,
    prefix = interaction,
  ) => {
    const response = await page.request.post(`${fake}/dialogue/${city.id}`, {
      data: { participants, interaction, count, prefix },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
    return (await response.json()) as { lines: Dialogue[]; revision: number };
  };
  const pair = world.agents.slice(0, 2);
  await commit(
    pair.map((a) => a.id),
    "watched_chat",
  );
  await page.goto(`/simulations/${city.id}`);
  await expect(page.locator(".connection")).toHaveText("LIVE");
  return { city, world, pair, commit };
}
async function watch(page: Page) {
  await page.getByRole("button", { name: /^Conversations/ }).click();
  await page.getByRole("button", { name: "See them up close" }).click();
}

test("LV-03 real reconnect and polling snapshots never repeat handled turns", async ({
  page,
  request,
}) => {
  let drop = false,
    watched: WebSocketRoute | undefined;
  await page.routeWebSocket("**/stream", (socket) => {
    if (drop) socket.close({ code: 1001 });
    else {
      watched = socket;
      socket.connectToServer();
    }
  });
  const { city, pair, commit } = await prepare(page);
  await watch(page);
  await monitor(page);
  const voices = page.getByRole("region", { name: "Live voices" });
  await expect(
    voices.getByRole("button", { name: "Enable live voices" }),
  ).toBeHidden();
  await voices.getByRole("button", { name: "Show city radio" }).click();
  await voices.getByRole("button", { name: "Hide city radio" }).click();
  await expect(
    voices.getByRole("button", { name: "Enable live voices" }),
  ).toBeHidden();
  await voices.getByRole("button", { name: "Show city radio" }).click();
  await voices.getByRole("button", { name: "Enable live voices" }).click();
  await commit(
    pair.map((a) => a.id),
    "watched_chat",
    2,
    "Before reconnect",
  );
  await expect.poll(async () => (await played(page)).length).toBe(2);
  drop = true;
  await watched!.close({ code: 1001 });
  await expect(page.locator(".connection")).toHaveText("POLLING", {
    timeout: 20_000,
  });
  await commit(
    pair.map((a) => a.id),
    "watched_chat",
    2,
    "During polling",
  );
  await expect.poll(async () => (await played(page)).length).toBe(4);
  const count = (await (await request.get(`${fake}/requests`)).json()).length;
  for (let n = 0; n < 2; n++) {
    const simulation = await api<Simulation>(page, `/simulations/${city.id}`);
    await api(page, `/simulations/${city.id}/commands`, "POST", {
      request_id: randomUUID(),
      expected_control_version: simulation.control_version,
      command: { type: "set_speed", value: 1 },
    });
  }
  drop = false;
  await expect(page.locator(".connection")).toHaveText("LIVE", {
    timeout: 20_000,
  });
  expect((await played(page)).length).toBe(4);
  expect((await (await request.get(`${fake}/requests`)).json()).length).toBe(
    count,
  );
});
type Played = {
  source: string;
  caption: string;
  active: number;
  at: number;
  endedAt: number;
};
async function monitor(page: Page) {
  await page.evaluate(() => {
    const state = window as unknown as { played: Played[]; lastEnded: number };
    state.played = [];
    state.lastEnded = 0;
    document.addEventListener(
      "ended",
      (event) => {
        if (
          (event.target as Element).getAttribute("aria-label") ===
          "Live conversation voice"
        )
          state.lastEnded = performance.now();
      },
      true,
    );
    document.addEventListener(
      "playing",
      (event) => {
        const audio = event.target as HTMLAudioElement;
        if (audio.currentSrc.startsWith("data:")) return;
        if (audio.getAttribute("aria-label") !== "Live conversation voice")
          return;
        const at = performance.now(),
          endedAt = state.lastEnded;
        setTimeout(
          () =>
            state.played.push({
              source: audio.currentSrc,
              caption:
                document.querySelector(".spoken-caption")?.textContent ?? "",
              active: [...document.querySelectorAll("audio")].filter(
                (a) => !a.paused,
              ).length,
              at,
              endedAt,
            }),
          0,
        );
      },
      true,
    );
  });
}
const played = (page: Page) =>
  page.evaluate(() => (window as unknown as { played: Played[] }).played);

test("LV-01/02/10 four committed turns play automatically with distinct voices, captions and one channel", async ({
  page,
  request,
}, info) => {
  const { city, world, pair, commit } = await prepare(page);
  await watch(page);
  await monitor(page);
  const voices = page.getByRole("region", { name: "Live voices" });
  await expect(
    voices.getByRole("button", { name: "Enable live voices" }),
  ).toBeHidden();
  await voices.getByRole("button", { name: "Show city radio" }).click();
  await voices.getByRole("button", { name: "Enable live voices" }).click();
  const before = await (await request.get(`${fake}/requests`)).json();
  const committed = await commit(
    pair.map((a) => a.id),
    "watched_chat",
    4,
    "Four real turns",
  );
  await commit(
    world.agents.slice(2, 4).map((a) => a.id),
    "unrelated_chat",
    2,
    "Background should be silent",
  );
  await expect.poll(async () => (await played(page)).length).toBe(4);
  const events = await played(page);
  writeFileSync(
    "artifacts/narration/live-voices-playback.json",
    JSON.stringify(
      {
        controlledProvider: true,
        activePlayerCounts: events.map((e) => e.active),
        cachedTransitionMs: events
          .slice(1)
          .map((e) => Math.round((e.at - e.endedAt) * 100) / 100),
        playedLines: committed.lines.map((l) => ({
          id: l.id,
          speaker: l.speaker_id,
          text: l.text,
        })),
      },
      null,
      2,
    ) + "\n",
  );
  expect(events.every((e) => e.active === 1)).toBeTruthy();
  const calls = (await (await request.get(`${fake}/requests`)).json()).slice(
    before.length,
  ) as { text: string; path: string }[];
  expect(calls.map((c) => c.text)).toEqual(committed.lines.map((l) => l.text));
  expect(new Set(calls.map((c) => c.path)).size).toBe(2);
  expect(calls[0].path).toBe(calls[2].path);
  expect(calls[1].path).toBe(calls[3].path);
  for (let n = 0; n < 4; n++) {
    expect(events[n].caption).toContain(pair[n % 2].name);
    expect(events[n].caption).toContain(committed.lines[n].text);
    const response = await page.request.get(events[n].source);
    const marker =
      "agentcity-narration:" +
      createHash("sha256")
        .update(committed.lines[n].text)
        .digest("hex")
        .slice(0, 32);
    expect((await response.body()).includes(Buffer.from(marker))).toBeTruthy();
    if (n > 0) expect(events[n].at - events[n].endedAt).toBeLessThan(250);
  }
  expect((await api<Simulation>(page, `/simulations/${city.id}`)).status).toBe(
    "paused",
  );
  await info.attach("live-voice-playback", {
    body: JSON.stringify({ events, calls }, null, 2),
    contentType: "application/json",
  });
  await page.screenshot({
    path: "artifacts/narration/live-voices-desktop.png",
  });
});

test("LV-04/05/10 focus changes abort stale work; autoplay failure and mute are explicit", async ({
  page,
  request,
}) => {
  const { world, pair, commit } = await prepare(page);
  await watch(page);
  await monitor(page);
  const voices = page.getByRole("region", { name: "Live voices" });
  await expect(
    voices.getByRole("button", { name: "Enable live voices" }),
  ).toBeHidden();
  await voices.getByRole("button", { name: "Show city radio" }).click();
  await voices.getByRole("button", { name: "Enable live voices" }).click();
  await request.post(`${fake}/hold`);
  await commit(
    pair.map((a) => a.id),
    "watched_chat",
    1,
    "Stale pending turn",
  );
  await expect(voices).toContainText("Preparing committed dialogue");
  await page.getByRole("button", { name: "Close character focus" }).click();
  await page
    .getByRole("button", {
      name: `${world.agents[2].name}, ${world.agents[2].role}`,
      exact: true,
    })
    .press("Enter");
  await request.post(`${fake}/release`);
  await expect.poll(async () => (await played(page)).length).toBe(0);
  await page
    .getByRole("button", { name: /Their story & relationships/ })
    .click();
  await expect(
    page.getByRole("complementary", { name: "A closer look" }),
  ).toContainText(world.agents[2].name);
  await page.evaluate(() => {
    const original = HTMLMediaElement.prototype.play;
    let reject = true;
    HTMLMediaElement.prototype.play = function () {
      if (
        reject &&
        this.getAttribute("aria-label") === "Live conversation voice"
      ) {
        reject = false;
        return Promise.reject(new DOMException("Blocked", "NotAllowedError"));
      }
      return original.call(this);
    };
  });
  await commit(
    world.agents.slice(2, 4).map((a) => a.id),
    "new_chat",
    1,
    "Selected citizen reply",
  );
  await expect(voices.getByRole("alert")).toContainText(
    "Browser playback was blocked",
  );
  await voices.getByRole("button", { name: "Resume listening" }).click();
  await expect.poll(async () => (await played(page)).length).toBe(1);
  await voices.getByRole("button", { name: "Mute voices" }).click();
  const count = (await (await request.get(`${fake}/requests`)).json()).length;
  await commit(
    world.agents.slice(2, 4).map((a) => a.id),
    "new_chat",
    2,
    "Muted turns",
  );
  await page.waitForTimeout(500);
  expect((await (await request.get(`${fake}/requests`)).json()).length).toBe(
    count,
  );
  await page
    .getByRole("button", { name: "Close panel", exact: true })
    .last()
    .click();
  await voices.getByRole("button", { name: "Unmute voices" }).click();
  await page
    .getByRole("button", {
      name: `${pair[0].name}, ${pair[0].role}`,
      exact: true,
    })
    .press("Enter");
  await page.waitForTimeout(250);
  expect((await (await request.get(`${fake}/requests`)).json()).length).toBe(
    count,
  );
  await commit(
    pair.map((a) => a.id),
    "watched_chat",
    1,
    "Return to original citizen",
  );
  await expect.poll(async () => (await played(page)).length).toBe(2);
  await page.reload();
  await voices.getByRole("button", { name: "Show city radio" }).click();
  await expect(
    voices.getByRole("button", { name: "Enable live voices" }),
  ).toBeVisible();
  await expect(
    page.locator('audio[aria-label="Live conversation voice"]'),
  ).toHaveCount(0);
});

test("LV-06/09 overload is visible, replay is explicit, and mobile controls remain usable", async ({
  page,
  request,
}) => {
  const { pair, commit } = await prepare(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await watch(page);
  await monitor(page);
  const voices = page.getByRole("region", { name: "Live voices" });
  await expect(
    voices.getByRole("button", { name: "Enable live voices" }),
  ).toBeHidden();
  await voices.getByRole("button", { name: "Show city radio" }).click();
  const count = (await (await request.get(`${fake}/requests`)).json()).length;
  await voices.getByRole("button", { name: "Enable live voices" }).click();
  await voices
    .getByRole("button", { name: "Replay this conversation" })
    .click();
  await expect.poll(async () => (await played(page)).length).toBe(1);
  await voices.getByRole("button", { name: "Pause audio" }).click();
  await commit(
    pair.map((a) => a.id),
    "watched_chat",
    14,
    "Too much dialogue",
  );
  await expect(voices).toContainText("Missed/backlogged");
  expect((await (await request.get(`${fake}/requests`)).json()).length).toBe(
    count + 1,
  );
  await voices.getByRole("button", { name: "Catch up live" }).click();
  await expect(voices).not.toContainText("Missed/backlogged");
  const bounds = await voices.boundingBox();
  expect(bounds!.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: "artifacts/narration/live-voices-mobile.png" });
});
