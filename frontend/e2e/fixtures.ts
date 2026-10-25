import { test as base, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { defaultSettings } from "../src/api/defaults";
import type { Settings, Simulation } from "../src/api/types";

export { expect };
export type { Page, Request } from "@playwright/test";

// Both servers have disposable stores. Isolate server preferences as well as the
// browser context, and clean up new cities/profiles even when an assertion fails.
export const test = base.extend<{ isolatedApplication: void }>({
  isolatedApplication: [
    async ({ page }, use) => {
      const request = page.request;
      const origins = ["http://127.0.0.1:15173", "http://127.0.0.1:10801"];
      async function api<T>(
        origin: string,
        path: string,
        method = "GET",
        data?: unknown,
      ): Promise<T> {
        const session = await request.get(origin + "/api/v1/session");
        const response = await request.fetch(origin + "/api/v1" + path, {
          method,
          data,
          headers: {
            "X-CSRF-Token": (await session.json()).data.csrf_token,
            "Idempotency-Key":
              (data as { request_id?: string } | undefined)?.request_id ??
              randomUUID(),
          },
        });
        expect(
          response.ok(),
          `${method} ${path}: ${await response.text()}`,
        ).toBeTruthy();
        return (await response.json()).data;
      }
      async function cities(origin: string) {
        const result: Simulation[] = [];
        for (const archived of [false, true]) {
          let cursor: string | null = null;
          do {
            const query = new URLSearchParams({
              archived: String(archived),
              limit: "100",
            });
            if (cursor) query.set("cursor", cursor);
            const page = await api<{
              items: Simulation[];
              next_cursor: string | null;
            }>(origin, `/simulations?${query}`);
            result.push(...page.items);
            cursor = page.next_cursor;
          } while (cursor);
        }
        return result;
      }
      async function settings(
        origin: string,
        values: Omit<Settings, "version">,
      ) {
        const current = await api<Settings>(origin, "/settings");
        await api(origin, "/settings", "PUT", {
          expected_version: current.version,
          settings: values,
        });
      }
      const snapshots = [];
      for (const origin of origins) {
        const { version: _, ...previous } = await api<Settings>(
          origin,
          "/settings",
        );
        const { version: __, ...defaults } = defaultSettings;
        snapshots.push({
          origin,
          previous,
          cities: new Set((await cities(origin)).map((city) => city.id)),
          profiles: new Set(
            (
              await api<{ items: { id: string }[] }>(origin, "/custom-agents")
            ).items.map((p) => p.id),
          ),
        });
        await settings(origin, defaults);
      }
      try {
        await use();
      } finally {
        // Leaving the simulation closes sockets and UI mutation effects first.
        await page.goto("about:blank");
        for (const snapshot of snapshots) {
          try {
            for (let city of await cities(snapshot.origin)) {
              if (snapshot.cities.has(city.id)) continue;
              const fresh = () =>
                api<Simulation>(snapshot.origin, `/simulations/${city.id}`);
              await expect
                .poll(async () => (await fresh()).status)
                .not.toBe("initializing");
              city = await fresh();
              const command = async (type: string) => {
                city = await fresh();
                const key = randomUUID();
                await api(
                  snapshot.origin,
                  `/simulations/${city.id}/commands`,
                  "POST",
                  {
                    request_id: key,
                    expected_control_version: city.control_version,
                    command: { type },
                  },
                );
              };
              if (city.status === "running") await command("pause");
              if (!city.archived) await command("archive");
              await api(snapshot.origin, `/simulations/${city.id}`, "DELETE", {
                confirmation_name: city.name,
              });
            }
            const profiles = await api<{
              items: { id: string; version: number }[];
            }>(snapshot.origin, "/custom-agents");
            for (const profile of profiles.items) {
              if (!snapshot.profiles.has(profile.id))
                await api(
                  snapshot.origin,
                  `/custom-agents/${profile.id}`,
                  "DELETE",
                  { expected_version: profile.version },
                );
            }
          } finally {
            await settings(snapshot.origin, snapshot.previous);
          }
        }
      }
    },
    { auto: true },
  ],
});
