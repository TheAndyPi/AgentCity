export type NarrationSourceType = "event" | "decision" | "dialogue";
export interface NarrationAudio {
  audio_url: string;
  expires_at: string;
}

// Completed results are deliberately not cached here: a record's text can change
// (an event's summary advances), and the server cache is keyed by the actual text.
const inflight = new Map<string, Promise<NarrationAudio>>();

export const sourceKey = (
  simulationId: string,
  sourceType: NarrationSourceType,
  sourceId: string,
) => JSON.stringify([simulationId, sourceType, sourceId]);

export const pending = (key: string) => inflight.get(key);

/** One request per source at a time; a remounted player attaches to it. */
export function request(key: string, load: () => Promise<NarrationAudio>) {
  const existing = inflight.get(key);
  if (existing) return existing;
  const promise = load().finally(() => inflight.delete(key));
  inflight.set(key, promise);
  return promise;
}

export function resetNarrationRequests() {
  inflight.clear();
}
