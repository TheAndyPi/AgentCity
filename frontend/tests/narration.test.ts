import { beforeEach, describe, expect, it } from "vitest";
import {
  pending,
  request,
  resetNarrationRequests,
  sourceKey,
  type NarrationAudio,
} from "../src/narration/results";

const audio = (id: string): NarrationAudio => ({
  audio_url: `http://127.0.0.1/api/v1/integrations/narration/audio/${id}`,
  expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

describe("narration requests", () => {
  beforeEach(resetNarrationRequests);

  it("keys sources by simulation, type and record ID", () => {
    const keys = new Set([
      sourceKey("simulation_1", "event", "x"),
      sourceKey("simulation_1", "decision", "x"),
      sourceKey("simulation_2", "event", "x"),
      sourceKey("simulation_1", "event", "x"),
    ]);
    expect(keys.size).toBe(3);
  });

  it("shares one in-flight request per source, never across sources", async () => {
    const event = sourceKey("s", "event", "e1");
    const decision = sourceKey("s", "decision", "d1");
    const gate = deferred<NarrationAudio>();
    let calls = 0;
    const load = () => {
      calls += 1;
      return gate.promise;
    };
    const first = request(event, load);
    expect(request(event, load)).toBe(first);
    expect(pending(event)).toBe(first);
    expect(pending(decision)).toBeUndefined();
    expect(calls).toBe(1);
    const other = request(decision, async () => audio("d1"));
    expect(other).not.toBe(first);
    gate.resolve(audio("e1"));
    expect((await first).audio_url).toMatch(/e1$/);
    expect((await other).audio_url).toMatch(/d1$/);
    expect(pending(event)).toBeUndefined();
  });

  it("releases failed requests so an explicit retry issues a new call", async () => {
    const key = sourceKey("s", "dialogue", "l1");
    const failure = deferred<NarrationAudio>();
    const failed = request(key, () => failure.promise);
    failure.reject(new Error("provider unavailable"));
    await expect(failed).rejects.toThrow("provider unavailable");
    expect(pending(key)).toBeUndefined();
    let calls = 0;
    const retried = await request(key, async () => {
      calls += 1;
      return audio("retry");
    });
    expect(calls).toBe(1);
    expect(retried.audio_url).toMatch(/retry$/);
  });
});
