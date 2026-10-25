import { test, expect } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

async function setup(request: APIRequestContext) {
  const session = await request.get("/api/v1/session");
  const csrf = (await session.json()).data.csrf_token;
  async function write(path: string, body: unknown) {
    const response = await request.post(`/api/v1${path}`, {
      data: body,
      headers: { "Idempotency-Key": crypto.randomUUID(), "X-CSRF-Token": csrf },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
    return (await response.json()).data;
  }
  const created = await write("/simulations", {
    config: { name: "Snowflake browser A", seed: 42, population: 10 },
  });
  let a = created;
  await expect
    .poll(async () => {
      a = (
        await (await request.get(`/api/v1/simulations/${created.id}`)).json()
      ).data;
      return a.status;
    })
    .toBe("paused");
  const stepKey = crypto.randomUUID();
  const stepped = await request.post(`/api/v1/simulations/${a.id}/commands`, {
    data: {
      request_id: stepKey,
      expected_control_version: a.control_version,
      command: { type: "step", count: 2 },
    },
    headers: { "Idempotency-Key": stepKey, "X-CSRF-Token": csrf },
  });
  expect(stepped.ok()).toBeTruthy();
  a = (await stepped.json()).data.simulation;
  const branch = await write(`/simulations/${a.id}/branches`, {
    name: "Snowflake browser B",
    source: { kind: "whole" },
  });
  return { a, b: branch.simulation };
}

test("S-06 real application route shows exact query values and evidence; same-key retry after response loss", async ({
  page,
  request,
}) => {
  const { a, b } = await setup(request);
  const url = `/tests/visual/snowflake.html?a=${a.id}&ar=${a.revision}&b=${b.id}&br=${b.revision}`;
  let actual: any;
  let firstKey = "";
  let posts = 0;
  await page.route(
    "**/api/v1/integrations/snowflake/comparisons",
    async (route) => {
      posts++;
      const key = route.request().headers()["idempotency-key"];
      if (posts === 1) firstKey = key;
      else expect(key).toBe(firstKey);
      const response = await route.fetch(); // Execute the REAL app route; external SQL HTTP is faked in Python.
      const body = await response.json();
      if (posts === 1) {
        actual = body;
        await route.abort("connectionreset");
      } else {
        expect(body).toEqual(actual);
        await route.fulfill({ response });
      }
    },
  );
  await page.goto(url);
  await page.getByRole("button", { name: "Compare pinned histories" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByRole("button", { name: "Retry same comparison" }).click();
  await expect(
    page.getByText("Snowflake read-back", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Cortex selected verified facts", { exact: true }),
  ).toBeVisible();
  expect(posts).toBe(2);
  expect(actual.data.citations.length).toBeGreaterThan(0);
  for (const metric of actual.data.differences) {
    const row = page.getByRole("row").filter({
      has: page.getByRole("rowheader", { name: metric.metric, exact: true }),
    });
    await expect(row.getByRole("cell")).toHaveText([
      String(metric.a),
      String(metric.b),
      String(metric.delta_b_minus_a),
    ]);
  }
  await expect(
    page
      .getByText(`Revision ${a.revision} · tick ${a.tick}`, { exact: false })
      .first(),
  ).toBeVisible();
  await page.getByText(/Inspect recorded evidence/).click();
  for (const citation of actual.data.citations) {
    const response = await request.get(citation.url);
    expect(response.status()).toBe(200);
    await expect(
      page.getByRole("link", { name: citation.id, exact: true }),
    ).toBeVisible();
  }
});

test("S-06 disabled comparison performs no integration request", async ({
  page,
  request,
}) => {
  const { a, b } = await setup(request);
  let calls = 0;
  page.on("request", (r) => {
    if (r.url().includes("/integrations/")) calls++;
  });
  await page.goto(
    `/tests/visual/snowflake.html?a=${a.id}&ar=${a.revision}&b=${b.id}&br=${b.revision}&disabled=true`,
  );
  await expect(
    page.getByText(
      "Snowflake comparison is disabled. The history chart remains available.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Compare pinned histories" }),
  ).toHaveCount(0);
  expect(calls).toBe(0);
});
