import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Dialogue } from "../api/types";
import type { AgentCityClient } from "../api/client";

/** A bounded initial page, live messages immediately, and explicit older pages. */
export function useDialoguePages(
  client: AgentCityClient,
  id: string,
  revision: number | undefined,
  recent: Dialogue[],
  agentId?: string,
) {
  const scope = `${id}:${revision ?? "live"}:${agentId ?? "all"}`;
  const [pageScope, setPageScope] = useState(scope);
  const [pages, setPages] = useState<Dialogue[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const active = useRef(scope);
  active.current = scope;
  const live = useRef<{ scope: string; messages: Map<string, Dialogue> }>({
    scope,
    messages: new Map(),
  });
  if (live.current.scope !== scope)
    live.current = { scope, messages: new Map() };
  for (const line of recent)
    if (
      !agentId ||
      line.speaker_id === agentId ||
      line.recipient_ids.includes(agentId)
    )
      live.current.messages.set(line.id, line);
  while (live.current.messages.size > 1000)
    live.current.messages.delete(live.current.messages.keys().next().value!);
  useEffect(() => {
    let disposed = false;
    setPageScope(scope);
    setPages([]);
    setCursor(null);
    setError("");
    setLoading(true);
    client
      .dialoguePage(id, { revision, agentId, limit: 50 })
      .then((page) => {
        if (!disposed) {
          setPages(page.items);
          setCursor(page.next_cursor);
        }
      })
      .catch((e) => {
        if (!disposed) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [client, id, revision, agentId]);
  const loadOlder = useCallback(async () => {
    if (!cursor || loading || pageScope !== scope) return;
    const requestedScope = scope;
    setLoading(true);
    try {
      const page = await client.dialoguePage(id, {
        revision,
        cursor,
        agentId,
        limit: 50,
      });
      if (active.current !== requestedScope) return;
      setPages((previous) => [...previous, ...page.items]);
      setCursor(page.next_cursor);
      setError("");
    } catch (e) {
      if (active.current === requestedScope)
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (active.current === requestedScope) setLoading(false);
    }
  }, [client, id, revision, agentId, cursor, loading, scope]);
  const messages = useMemo(() => {
    const unique = new Map(
      (pageScope === scope ? pages : []).map((line) => [line.id, line]),
    );
    for (const line of live.current.messages.values())
      unique.set(line.id, line);
    return [...unique.values()];
  }, [pages, recent, agentId, scope, pageScope]);
  return {
    messages,
    loading,
    error,
    hasOlder: pageScope === scope && !!cursor,
    loadOlder,
  };
}
