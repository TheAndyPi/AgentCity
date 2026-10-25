import { afterEach, describe, expect, it, vi } from "vitest";
import { LiveTransport } from "../src/api/client";

afterEach(() => vi.restoreAllMocks());

describe("shared scenario and live-voice transport", () => {
  it("preserves the long scenario interpretation deadline", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}")));
    await new LiveTransport().request(
      "GET",
      "/test",
      undefined,
      undefined,
      95000,
    );
    expect(timeout).toHaveBeenCalledWith(95000);
    vi.unstubAllGlobals();
  });

  it("preserves cancellation for live voice requests", async () => {
    const controller = new AbortController();
    const fetch = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetch);
    await new LiveTransport().request(
      "GET",
      "/test",
      undefined,
      undefined,
      controller.signal,
    );
    const signal = fetch.mock.calls[0][1].signal as AbortSignal;
    expect(signal.aborted).toBe(false);
    controller.abort();
    expect(signal.aborted).toBe(true);
    vi.unstubAllGlobals();
  });
});
