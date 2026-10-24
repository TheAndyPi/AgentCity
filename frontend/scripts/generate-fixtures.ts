import { mkdirSync, writeFileSync } from "node:fs";
import { MockTransport } from "../src/api/mock";
import { AgentCityClient, type Transport } from "../src/api/client";
import { defaultConfig } from "../src/api/defaults";
import * as S from "../src/api/schemas";
import {
  fixtureDetail,
  fixturePreview,
  fixtureWorld,
} from "../src/api/fixtures";
const mock = new MockTransport();
const trace: unknown[] = [];
const recorder: Transport = {
  mode: "mock",
  async request(method, path, body, key) {
    const response = await mock.request(method, path, body, key);
    trace.push({
      request: {
        method,
        path,
        body: body ?? null,
        idempotency_key: key ?? null,
      },
      response,
    });
    return response;
  },
};
const client = new AgentCityClient(recorder);
await client.capabilities();
const created = await client.create(
  { ...defaultConfig, scenario_description: "A sudden flood" },
  crypto.randomUUID(),
);
let sim = created;
while (sim.status === "initializing") sim = await client.simulation(sim.id);
const initial = await client.initial(sim, "confirm", crypto.randomUUID());
sim = (await client.command(initial.simulation, { type: "step", count: 9 }))
  .simulation;
const report = await client.report(sim.id, initial.event!.id, sim.revision);
const branch = await client.branch(sim.id, "Restored review branch", {
  kind: "snapshot",
  snapshot_id: report.event.pre_event_snapshot_id,
});
await client.state(branch.simulation.id);
await client.agent(branch.simulation.id, "citizen-1");
mkdirSync("tests/fixtures", { recursive: true });
writeFileSync(
  "tests/fixtures/flow-trace.json",
  JSON.stringify({ mode: "mock", contract_version: "1.0.0", trace }, null, 2),
);
const fixtures = {
  ready: fixtureWorld(),
  preview: fixturePreview(fixtureWorld()),
  rejected_decision: fixtureDetail(fixtureWorld(), "citizen-3").decisions
    .items[0],
  report,
};
S.world.parse(fixtures.ready);
S.preview.parse(fixtures.preview);
S.decision.parse(fixtures.rejected_decision);
S.eventReport.parse(fixtures.report);
for (const [name, value] of Object.entries(fixtures))
  writeFileSync(`tests/fixtures/${name}.json`, JSON.stringify(value));
console.log(
  "Validated and recorded frontend-local fixtures and exact mock request/response trace.",
);
