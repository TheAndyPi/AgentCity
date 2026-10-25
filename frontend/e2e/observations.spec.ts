import { randomUUID } from "node:crypto";
import { test, expect, type Page } from "./fixtures";
import { defaultConfig } from "../src/api/defaults";
import type { Simulation, WorldFrame } from "../src/api/types";

async function api<T>(
  page: Page,
  path: string,
  method = "GET",
  data?: unknown,
): Promise<T> {
  const session = await (await page.request.get("/api/v1/session")).json();
  const response = await page.request.fetch(`/api/v1${path}`, {
    method,
    data,
    headers: {
      "X-CSRF-Token": session.data.csrf_token,
      "Idempotency-Key":
        (data as { request_id?: string })?.request_id ?? randomUUID(),
    },
  });
  expect(
    response.ok(),
    `${method} ${path}: ${await response.text()}`,
  ).toBeTruthy();
  return (await response.json()).data;
}

async function step(page: Page, sid: string) {
  const city = await api<Simulation>(page, `/simulations/${sid}`);
  await api(page, `/simulations/${sid}/commands`, "POST", {
    request_id: randomUUID(),
    expected_control_version: city.control_version,
    command: { type: "step", count: 1 },
  });
}

async function createCity(page: Page, openingEvent = false) {
  await page.goto("/");
  const created = await api<Simulation>(page, "/simulations", "POST", {
    config: {
      ...defaultConfig,
      name: `Observation browser ${Date.now()}`,
      population: 10,
      scenario_description: openingEvent
        ? "A flood severity 40 for 2 ticks"
        : "",
    },
  });
  await expect
    .poll(
      async () =>
        (await api<Simulation>(page, `/simulations/${created.id}`)).status,
    )
    .toBe("paused");
  await page.goto(`/simulations/${created.id}`);
  if (openingEvent) {
    await page
      .getByRole("button", { name: "Confirm opening event", exact: true })
      .click();
    await expect
      .poll(async () => {
        const city = await api<Simulation>(page, `/simulations/${created.id}`);
        return city.initial_preview === null && city.control_version >= 1;
      })
      .toBe(true);
    let resolved = false;
    for (let attempt = 0; attempt < 100; attempt++) {
      const city = await api<Simulation>(page, `/simulations/${created.id}`);
      if (city.pending_outcome_event_ids.length > 0) {
        resolved = true;
        break;
      }
      await step(page, created.id);
    }
    const finalCity = await api<Simulation>(page, `/simulations/${created.id}`);
    expect(resolved || finalCity.pending_outcome_event_ids.length > 0).toBe(
      true,
    );
    await page.getByRole("button", { name: "Continue", exact: true }).click();
  }
  await expect(page.locator(".connection")).toHaveText("LIVE");
  return api<WorldFrame>(page, `/simulations/${created.id}/state`);
}

async function openObservations(page: Page) {
  await page
    .getByRole("button", { name: "Open city menu", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Simulation overview", exact: true })
    .click();
  await page.getByRole("button", { name: "Observations", exact: true }).click();
  return page.locator(".observations-panel");
}

/** Only warehouse responses are fixtures; city state, navigation and session use the real backend. */
async function fixtureWarehouse(page: Page, frame: WorldFrame) {
  const requests: URL[] = [];
  const event = frame.events[0]
    ? {
        event_id: frame.events[0].id,
        title: frame.events[0].title,
        status: "resolved",
        start_tick: 1,
        end_tick: 3,
      }
    : null;
  await page.route(
    "**/api/v1/integrations/snowflake/observations/v1/simulations/**",
    async (route) => {
      const url = new URL(route.request().url());
      requests.push(url);
      const revision = Number(url.searchParams.get("through_revision"));
      const common = {
        source: "snowflake",
        simulation_id: frame.simulation.id,
        requested_revision: revision,
        effective_revision: revision,
        coverage: {
          state: "complete",
          from_tick: 0,
          through_tick: frame.ref.tick,
        },
      };
      const catalog = [
        {
          id: "health",
          label: "Health",
          unit: "population_mean_0_100",
          denominator: "Living active agents",
        },
        {
          id: "trust",
          label: "Community trust",
          unit: "population_mean_0_100",
          denominator: "Living active agents",
        },
        {
          id: "relationship_pairs",
          label: "Known relationship pairs",
          unit: "recorded_count",
          denominator: "Known unique unordered pairs",
        },
      ];
      const change = {
        id: "fixture_health_change",
        tick: 3,
        revision,
        entity_kind: "agent",
        entity_id: frame.agents[0].id,
        agent_id: frame.agents[0].id,
        field: "health",
        before: 100,
        after: 90,
        link: "explicit",
        event_ids: event ? [event.event_id] : [],
        evidence: { description: "Explicit browser warehouse fixture" },
      };
      let result: Record<string, unknown>;
      if (url.pathname.endsWith("/status"))
        result = {
          enabled: true,
          state: "healthy",
          published_revision: revision,
          ingested_revision: revision,
          lag_revisions: 0,
          error_code: null,
        };
      else if (url.pathname.endsWith("/metrics")) result = { items: catalog };
      else if (url.pathname.endsWith("/trends")) {
        const metric = url.searchParams.get("metric") ?? "health";
        const value =
          metric === "trust" ? 60 : metric === "relationship_pairs" ? 3 : 90;
        result = {
          metric,
          unit: catalog.find((item) => item.id === metric)!.unit,
          items: [
            {
              tick: 0,
              revision: 0,
              mean: metric === "trust" ? 50 : metric === "health" ? 100 : 2,
              min: metric === "health" ? 100 : 2,
              max: metric === "health" ? 100 : 50,
              sample_count: 1,
              denominator: 10,
            },
            {
              tick: Math.max(1, frame.ref.tick),
              revision,
              mean: value,
              min: value,
              max: value,
              sample_count: 1,
              denominator: 10,
            },
          ],
          events: event ? [event] : [],
          distribution:
            metric === "relationship_pairs"
              ? [
                  { label: "friend / rival", count: 1 },
                  { label: "friend", count: 2 },
                ]
              : [],
        };
      } else if (url.pathname.endsWith("/events"))
        result = { items: event ? [event] : [], next_after: null };
      else if (url.pathname.endsWith("/changes"))
        result = { items: [change], next_after: null };
      else
        result = {
          event,
          baseline: {
            tick: 0,
            city: { health: 100, population: 10 },
            cohort: { health: 100, population: 10, deaths: 0 },
          },
          resolution: {
            tick: 3,
            city: { health: 90, population: 10 },
            cohort: { health: 90, population: 10, deaths: 0 },
          },
          followup: {
            tick: 3,
            city: { health: 90 },
            cohort: { health: 90, deaths: 0 },
          },
          followup_complete: false,
          change_counts: { explicit: 1, temporal: 0 },
          observations: [
            {
              id: "health_delta",
              text: "Health changed from 100 to 90 during the event interval.",
              citation_ids: ["fixture_citation"],
            },
          ],
          citations: [
            {
              id: "fixture_citation",
              tick: 3,
              revision,
              description: "Explicit warehouse UI fixture: health change",
            },
          ],
          overlaps: [],
          changes: [change],
        };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          schema_version: "1.0.0",
          request_id: randomUUID(),
          data: { ...common, ...result },
        }),
      });
    },
  );
  return requests;
}

test("observation panel shows the real disabled warehouse state", async ({
  page,
}) => {
  const frame = await createCity(page);
  const response = page.waitForResponse((r) =>
    r
      .url()
      .includes(`/observations/v1/simulations/${frame.simulation.id}/status`),
  );
  const panel = await openObservations(page);
  expect((await response).status()).toBe(200);
  await expect(panel).toContainText("Observations disabled");
  await expect(panel).toContainText("Existing local graphs remain available");
  await expect(panel.locator(".observations-chart")).toHaveCount(0);
});

test("warehouse UI fixtures agree across graph/table, filters and real citizen/event drilldowns", async ({
  page,
}, info) => {
  const frame = await createCity(page, true);
  const requests = await fixtureWarehouse(page, frame);
  const panel = await openObservations(page);
  await expect(panel).toContainText("Warehouse up to date");
  await expect(panel.getByRole("img")).toHaveAccessibleName(/Health, ticks/);
  await panel.getByText(/Trend data table ·/).click();
  await expect(
    panel.getByRole("row").filter({ hasText: "90–90" }),
  ).toContainText("90");
  await panel.getByLabel("Measure", { exact: true }).selectOption("trust");
  await expect(panel.getByRole("img")).toHaveAccessibleName(
    /Community trust, ticks/,
  );
  await panel.getByText(/Trend data table ·/).click();
  await expect(
    panel.getByRole("row").filter({ hasText: "60–60" }),
  ).toContainText("60");
  await panel
    .getByLabel("Measure", { exact: true })
    .selectOption("relationship_pairs");
  await expect(
    panel.getByRole("meter", { name: "friend / rival: 1" }),
  ).toBeVisible();
  await panel
    .getByLabel("Citizen", { exact: true })
    .selectOption(frame.agents[0].id);
  await expect
    .poll(
      () =>
        requests.filter(
          (url) =>
            url.pathname.endsWith("/trends") &&
            url.searchParams.get("agent_id") === frame.agents[0].id,
        ).length,
    )
    .toBeGreaterThan(0);
  await panel
    .getByRole("button", { name: "Inspect selected citizen", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Observe this citizen", exact: true })
    .click();
  await expect(
    page.locator(".observations-panel").getByLabel("Citizen", { exact: true }),
  ).toHaveValue(frame.agents[0].id);
  await page
    .locator(".observations-panel")
    .getByLabel("Event", { exact: true })
    .selectOption(frame.events[0].id);
  await expect(
    page.getByRole("region", { name: "Event measurements" }),
  ).toContainText("Health changed from 100 to 90");
  await expect(
    page.getByRole("region", { name: "Event measurements" }),
  ).toContainText("Follow-up is partial");
  await page
    .locator(".observations-panel")
    .getByText(/Events in this history ·/)
    .click();
  await page
    .locator(".observations-panel")
    .getByRole("button", { name: "Inspect event", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Observe event changes", exact: true })
    .click();
  await expect(
    page.locator(".observations-panel").getByLabel("Event", { exact: true }),
  ).toHaveValue(frame.events[0].id);
  await page.screenshot({
    path: info.outputPath("observations-fixture-interface.png"),
    fullPage: true,
  });
});

test("a historical observation popup keeps its requested revision while the real city advances", async ({
  page,
}) => {
  const frame = await createCity(page);
  const requests = await fixtureWarehouse(page, frame);
  await page.goto("/simulations");
  await page
    .getByRole("article", {
      name: `${frame.simulation.name}. Open the simulation overview`,
    })
    .click();
  await page.getByRole("button", { name: "Observations", exact: true }).click();
  const panel = page.locator(".observations-panel");
  await expect(panel).toContainText("Historical view");
  await expect(panel.getByRole("img")).toBeVisible();
  const pinned = Number(
    requests
      .find((url) => url.pathname.endsWith("/trends"))!
      .searchParams.get("through_revision"),
  );
  await step(page, frame.simulation.id);
  const advanced = await api<Simulation>(
    page,
    `/simulations/${frame.simulation.id}`,
  );
  expect(advanced.revision).toBeGreaterThan(pinned);
  await panel
    .getByRole("button", { name: "Refresh observations", exact: true })
    .click();
  await expect(panel.getByRole("img")).toBeVisible();
  expect(
    requests.every(
      (url) => Number(url.searchParams.get("through_revision")) === pinned,
    ),
  ).toBe(true);
});
