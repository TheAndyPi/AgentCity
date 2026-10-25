import { useEffect, useState } from "react";
import type { AgentCityClient } from "../api/client";
import { loadDisasters, type DisasterState } from "./client";
export function useDisasters(
  client: AgentCityClient,
  sid: string | undefined,
  revision: number | undefined,
  pinned = false,
) {
  const [value, setValue] = useState<DisasterState | null>(null);
  useEffect(() => {
    setValue((old) => (old?.simulation_id === sid ? old : null));
    if (!sid || revision === undefined || client.mode === "mock") return;
    const abort = new AbortController();
    let alive = true;
    void loadDisasters(client, sid, revision, abort.signal)
      .then((v) => {
        if (alive) setValue(v);
      })
      .catch(() => {
        if (alive) setValue(null);
      });
    return () => {
      alive = false;
      abort.abort();
    };
  }, [client, sid, revision]);
  return value &&
    value.simulation_id === sid &&
    revision !== undefined &&
    (pinned ? value.ref.revision === revision : value.ref.revision <= revision)
    ? value
    : null;
}
