import type { EventSummary } from "../api/types";

export function eventCauseNames(
  ids: readonly string[],
  events: readonly Pick<EventSummary, "id" | "title">[],
): string {
  const names = new Map(events.map((event) => [event.id, event.title]));
  return (
    ids.map((id) => names.get(id)?.trim() || "Unknown event").join(", ") ||
    "None"
  );
}
