import {
  test,
  expect,
  type APIRequestContext,
  type Locator,
  type Page,
} from "@playwright/test";
import { createHash, randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import type {
  AgentSummary,
  Decision,
  Settings,
  Simulation,
  WorldFrame,
} from "../src/api/types";

// N-07: real UI, real AgentCity API and media route; only ElevenLabs is faked.
const FAKE = "http://127.0.0.1:10830/__fake-elevenlabs";
const MEDIA =
  /^http:\/\/127\.0\.0\.1:15175\/api\/v1\/integrations\/narration\/audio\/[0-9a-f]{32}\?expires=\d+&signature=[0-9a-f]{64}$/;
const evidence = resolve("artifacts/narration");
mkdirSync(evidence, { recursive: true });

type VendorRequest = {
  text: string;
  model_id: string;
  path: string;
  output_format: string;
  authenticated: boolean;
};

async function api<T>(
  page: Page,
  path: string,
  method = "GET",
  data?: unknown,
): Promise<T> {
  const session = await page.request.get("/api/v1/session");
  const csrf = (await session.json()).data.csrf_token;
  const key = (data as { request_id?: string })?.request_id || randomUUID();
  const response = await page.request.fetch(`/api/v1${path}`, {
    method,
    data,
    headers: { "X-CSRF-Token": csrf, "Idempotency-Key": key },
  });
  expect(response.ok(), `${method} ${path}: ${await response.text()}`).toBe(
    true,
  );
  return (await response.json()).data;
}

async function command(page: Page, id: string, action: object) {
  const simulation = await api<Simulation>(page, `/simulations/${id}`);
  const key = randomUUID();
  return api(page, `/simulations/${id}/commands`, "POST", {
    request_id: key,
    expected_control_version: simulation.control_version,
    command: action,
  });
}

const vendor = {
  hold: (r: APIRequestContext) => r.post(`${FAKE}/hold`),
  release: (r: APIRequestContext) => r.post(`${FAKE}/release`),
  fail: (r: APIRequestContext, actions: unknown[]) =>
    r.post(`${FAKE}/fail`, { data: { actions } }),
  requests: async (r: APIRequestContext) =>
    (await (await r.get(`${FAKE}/requests`)).json()) as VendorRequest[],
};

const marker = (text: string) =>
  "agentcity-narration:" +
  createHash("sha256").update(text).digest("hex").slice(0, 32);
const sentence = (text: string) => (/[.!?:;]$/.test(text) ? text : `${text}.`);

async function mediaState(audio: Locator) {
  return audio.evaluate(
    (element: HTMLAudioElement) =>
      new Promise<{
        readyState: number;
        duration: number;
        error: number | null;
        paused: boolean;
        autoplay: boolean;
        currentSrc: string;
      }>((done) => {
        const report = () =>
          done({
            readyState: element.readyState,
            duration: element.duration,
            error: element.error?.code ?? null,
            paused: element.paused,
            autoplay: element.autoplay,
            currentSrc: element.currentSrc,
          });
        if (element.readyState >= 1 || element.error) return report();
        element.addEventListener("loadedmetadata", report, { once: true });
        element.addEventListener("error", report, { once: true });
      }),
  );
}

async function expectPlayable(page: Page, audio: Locator, text: string) {
  await expect(audio).toHaveAttribute("src", MEDIA);
  const state = await mediaState(audio);
  expect(state.error).toBeNull();
  expect(state.readyState).toBeGreaterThanOrEqual(1);
  expect(state.duration).toBeGreaterThan(0.3);
  // Loading metadata must not start playback.
  expect(state.paused).toBe(true);
  expect(state.autoplay).toBe(false);
  const played = await audio.evaluate(async (element: HTMLAudioElement) => {
    element.muted = true;
    await element.play();
    const started = performance.now();
    while (element.currentTime <= 0.05 && !element.ended) {
      if (performance.now() - started > 5000) break;
      await new Promise((r) => setTimeout(r, 20));
    }
    element.pause();
    element.currentTime = 0;
    return { currentTime: element.currentTime, error: element.error?.code };
  });
  expect(played.error ?? null).toBeNull();
  const fetched = await page.evaluate(
    async (src) => {
      const response = await fetch(src);
      const bytes = new Uint8Array(await response.arrayBuffer());
      return {
        status: response.status,
        type: response.headers.get("content-type"),
        head: new TextDecoder("latin1").decode(bytes.slice(0, 160)),
        size: bytes.length,
      };
    },
    await audio.getAttribute("src"),
  );
  expect(fetched.status).toBe(200);
  expect(fetched.type).toBe("audio/mpeg");
  expect(fetched.size).toBeGreaterThan(2000);
  expect(fetched.head).toContain(marker(text));
}

test("existing narration control plays the selected record without stale or automatic playback", async ({
  page,
  request,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const narrationPosts: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/narration"))
      narrationPosts.push(r.postData() ?? "");
  });
  await vendor.release(request);
  const settings = await api<Settings>(page, "/settings");
  const { version, ...values } = settings;
  await api(page, "/settings", "PUT", {
    expected_version: version,
    settings: { ...values, view_mode: "2d", reduce_motion: true },
  });
  expect(
    (await api<{ narration: boolean }>(page, "/capabilities")).narration,
  ).toBe(true);
  const created = await api<Simulation>(page, "/simulations", "POST", {
    config: {
      name: `Narration ${Date.now()}`,
      seed: 42,
      population: 10,
      scenario_description: "A flood for 2 ticks",
    },
  });
  const id = created.id;
  await expect
    .poll(
      async () => (await api<Simulation>(page, `/simulations/${id}`)).status,
    )
    .toBe("paused");
  const ready = await api<Simulation>(page, `/simulations/${id}`);
  await api(page, `/simulations/${id}/initial-scenario`, "POST", {
    preview_id: ready.initial_preview!.id,
    decision: "confirm",
    expected_control_version: ready.control_version,
  });

  await page.goto(`/simulations/${id}`);
  await expect(page.locator(".connection")).toHaveText("LIVE");

  // Event: loading state, then playable media for the recorded event text.
  await page.locator(".event-notice button").click();
  const eventDrawer = page.getByRole("complementary", {
    name: "A turning point",
  });
  const eventNarration = eventDrawer.locator(".narration");
  const frame = await api<WorldFrame>(page, `/simulations/${id}/state`);
  const event = frame.events[0];
  await expect(eventNarration).toHaveAttribute(
    "data-source",
    `event:${event.id}`,
  );
  await expect(page.locator("audio")).toHaveCount(0);
  const eventText = `${sentence(event.title)} ${event.summary}`;
  await vendor.hold(request);
  await eventNarration
    .getByRole("button", { name: "Listen to this record" })
    .click();
  await expect(
    eventNarration.getByRole("button", { name: "Preparing narration…" }),
  ).toBeDisabled();
  await expect(eventNarration.getByRole("status")).toHaveText(
    "Generating audio from the recorded text",
  );
  await vendor.release(request);
  const eventAudio = eventNarration.locator("audio");
  await expectPlayable(page, eventAudio, eventText);
  const firstSrc = await eventAudio.getAttribute("src");
  let calls = await vendor.requests(request);
  expect(calls).toEqual([
    {
      text: eventText,
      model_id: "eleven_test_model",
      path: "/v1/text-to-speech/TestVoice01",
      output_format: "mp3_44100_128",
      authenticated: true,
    },
  ]);
  await page.screenshot({ path: resolve(evidence, "event-narration.png") });

  // Ticks re-render the open drawer without regenerating or replacing audio.
  await command(page, id, { type: "step", count: 2 });
  await expect(eventDrawer.locator(".revision-label")).toHaveText("Tick 2");
  await expect(eventAudio).toHaveAttribute("src", firstSrc!);
  expect(await vendor.requests(request)).toHaveLength(1);
  expect(narrationPosts).toHaveLength(1);
  await eventDrawer.getByRole("button", { name: "Close panel" }).last().click();

  // Choose a citizen whose two recorded decisions produce different speech.
  const agents = (
    await api<{ items: AgentSummary[] }>(
      page,
      `/simulations/${id}/agents?limit=100`,
    )
  ).items;
  let chosen: { agent: AgentSummary; decisions: Decision[] } | undefined;
  for (const agent of agents) {
    const decisions = (
      await api<{ items: Decision[] }>(
        page,
        `/simulations/${id}/agents/${agent.id}/decisions`,
      )
    ).items;
    const texts = new Set(
      decisions.map((d) => d.concise_rationale + d.outcome_description),
    );
    if (decisions.length >= 2 && texts.size >= 2) {
      chosen = { agent, decisions };
      break;
    }
  }
  expect(chosen, "a citizen with two distinct decisions").toBeTruthy();
  const decisionText = (decision: Decision) =>
    `${sentence(chosen!.agent.name)} ${sentence(decision.concise_rationale)} ${decision.outcome_description}`;
  const byId = new Map(chosen!.decisions.map((d) => [d.id, d]));

  const openDecision = async (index: number) => {
    await page.getByRole("tab", { name: "Story", exact: true }).click();
    await page.locator(".decision-card").nth(index).click();
    const drawer = page.getByRole("complementary", { name: "Why this action" });
    const narration = drawer.locator(".narration");
    const source = await narration.getAttribute("data-source");
    return { drawer, narration, decision: byId.get(source!.split(":")[1])! };
  };
  await page
    .getByRole("button", { name: "Find a citizen", exact: true })
    .click();
  await page.getByLabel("Search citizens").fill(chosen!.agent.name);
  await page
    .getByLabel("All agents")
    .getByRole("button", { name: new RegExp(chosen!.agent.name) })
    .click();
  await page
    .getByRole("button", { name: `Open ${chosen!.agent.name} profile` })
    .click();

  // Start a slow request for the first decision, then switch to the second.
  const first = await openDecision(0);
  expect(first.decision).toBeTruthy();
  await vendor.hold(request);
  const firstPost = page.waitForResponse((r) => r.url().endsWith("/narration"));
  await first.narration
    .getByRole("button", { name: "Listen to this record" })
    .click();
  await expect(first.narration).toHaveAttribute("data-status", "loading");
  await page.getByRole("button", { name: "Back to previous panel" }).click();
  const second = await openDecision(1);
  expect(second.decision.id).not.toBe(first.decision.id);
  await expect(second.narration).toHaveAttribute("data-status", "idle");
  await vendor.release(request);
  expect((await firstPost).status()).toBe(200);
  await page.waitForTimeout(300);
  await expect(second.narration).toHaveAttribute("data-status", "idle");
  await expect(page.locator("audio")).toHaveCount(0);
  calls = await vendor.requests(request);
  expect(calls.map((c) => c.text)).toEqual([
    eventText,
    decisionText(first.decision),
  ]);

  // A provider failure shows a useful error; Retry succeeds for this source.
  await vendor.fail(request, [
    ["status", 503],
    ["status", 503],
    ["status", 503],
  ]);
  await second.narration
    .getByRole("button", { name: "Listen to this record" })
    .click();
  await expect(second.narration.getByRole("alert")).toContainText(
    "The speech provider is unavailable",
  );
  await expect(page.locator("audio")).toHaveCount(0);
  await second.narration.getByRole("button", { name: "Try again" }).click();
  await expectPlayable(
    page,
    second.narration.locator("audio"),
    decisionText(second.decision),
  );
  calls = await vendor.requests(request);
  expect(calls).toHaveLength(6);
  expect(calls[5].text).toBe(decisionText(second.decision));
  await page.screenshot({ path: resolve(evidence, "decision-retry.png") });

  // Returning to the first decision shows its own control, not stale audio.
  // Its media fails once in the browser; Retry receives a fresh cached URL.
  await page.getByRole("button", { name: "Back to previous panel" }).click();
  const revisit = await openDecision(0);
  expect(revisit.decision.id).toBe(first.decision.id);
  await expect(revisit.narration).toHaveAttribute("data-status", "idle");
  let blocked = 0;
  await page.route(
    "**/api/v1/integrations/narration/audio/**",
    async (route) => {
      blocked += 1;
      await route.fulfill({ status: 404, body: "unavailable" });
    },
  );
  await revisit.narration
    .getByRole("button", { name: "Listen to this record" })
    .click();
  await expect(revisit.narration.getByRole("alert")).toContainText(
    "could not be played",
  );
  expect(blocked).toBeGreaterThan(0);
  await page.unroute("**/api/v1/integrations/narration/audio/**");
  await revisit.narration.getByRole("button", { name: "Try again" }).click();
  await expectPlayable(
    page,
    revisit.narration.locator("audio"),
    decisionText(first.decision),
  );
  expect(await vendor.requests(request)).toHaveLength(6);
  expect(errors).toEqual([]);
  await info.attach("vendor-requests", {
    body: JSON.stringify(await vendor.requests(request), null, 2),
    contentType: "application/json",
  });
});
