import type { FrameDelta, WorldFrame } from "../api/types";
import { AgentCityClient, websocketUrl } from "../api/client";
import * as S from "../api/schemas";
export type Connection =
  | "connecting"
  | "live"
  | "reconnecting"
  | "polling"
  | "error"
  | "mock";
export class WorldStore {
  private state: {
    frame: WorldFrame | null;
    connection: Connection;
    error: string | null;
  } = { frame: null, connection: "connecting", error: null };
  private listeners = new Set<() => void>();
  private notification: number | null = null;
  generation = 0;
  private expectedId: string | null = null;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  getSnapshot = () => this.state;
  update(patch: Partial<typeof this.state>) {
    this.state = { ...this.state, ...patch };
    if (typeof requestAnimationFrame === "undefined") {
      this.listeners.forEach((l) => l());
    } else if (this.notification === null) {
      this.notification = requestAnimationFrame(() => {
        this.notification = null;
        this.listeners.forEach((l) => l());
      });
    }
  }
  accept(frame: WorldFrame, generation = this.generation) {
    if (generation !== this.generation) return false;
    if (this.expectedId && frame.simulation.id !== this.expectedId)
      return false;
    const current = this.state.frame;
    if (current && current.simulation.id !== frame.simulation.id) return false;
    if (current && frame.ref.revision <= current.ref.revision) return false;
    this.update({ frame, error: null });
    return true;
  }
  acceptDelta(frame: FrameDelta, generation = this.generation) {
    if (generation !== this.generation) return false;
    const current = this.state.frame;
    if (current && frame.ref.revision <= current.ref.revision) return false;
    if (
      !frame.map &&
      (!current ||
        current.simulation.id !== frame.simulation.id ||
        (current.map_version ?? 0) !== (frame.map_version ?? 0))
    )
      throw new Error("Stream map version needs a snapshot");
    let map = frame.map ?? current!.map;
    if (frame.map_updates) {
      const zones = new Map(
        frame.map_updates.zones.map((zone) => [zone.id, zone]),
      );
      const buildings = new Map(
        frame.map_updates.buildings.map((building) => [building.id, building]),
      );
      const resources = new Map(
        frame.map_updates.resources.map((resource) => [resource.id, resource]),
      );
      map = {
        ...map,
        zones: map.zones.map((zone) => ({ ...zone, ...zones.get(zone.id) })),
        buildings: map.buildings.map((building) => ({
          ...building,
          ...buildings.get(building.id),
        })),
        resources: map.resources.map((resource) => ({
          ...resource,
          ...resources.get(resource.id),
        })),
      };
    }
    const { map_updates: _updates, ...world } = frame;
    return this.accept({ ...world, map }, generation);
  }
  start(id: string, client: AgentCityClient) {
    this.generation++;
    this.expectedId = id;
    const gen = this.generation;
    this.update({
      frame: null,
      connection: client.mode === "mock" ? "mock" : "connecting",
      error: null,
    });
    let closed = false;
    let socket: WebSocket | undefined;
    let retry: ReturnType<typeof setTimeout>;
    let poll: ReturnType<typeof setInterval> | undefined;
    let heartbeat: ReturnType<typeof setInterval> | undefined;
    let attempts = 0;
    let lastTraffic = Date.now();
    const fetchState = () =>
      client
        .state(id)
        .then((f) => {
          if (!closed) this.accept(f, gen);
        })
        .catch((e) => {
          if (!closed) this.update({ error: e.message });
        });
    void fetchState();
    const off = client.transport.subscribe?.(id, (f) => this.accept(f, gen));
    const connect = () => {
      if (closed || client.mode === "mock") return;
      const current = new WebSocket(websocketUrl(id));
      socket = current;
      let ended = false;
      const active = () =>
        !closed && !ended && gen === this.generation && socket === current;
      current.onopen = () => {
        if (!active()) return;
        lastTraffic = Date.now();
        current.send(
          JSON.stringify({
            type: "hello",
            schema_version: "1.0.0",
            last_revision: this.state.frame?.ref.revision ?? null,
          }),
        );
      };
      current.onmessage = (e) => {
        if (!active()) return;
        lastTraffic = Date.now();
        try {
          const m = S.serverMessage.parse(JSON.parse(e.data));
          if (m.simulation_id !== id) return;
          if (m.type === "snapshot" || m.type === "frame") {
            if (m.type === "snapshot") this.accept(m.data, gen);
            else this.acceptDelta(m.data, gen);
            attempts = 0;
            this.update({ connection: "live" });
            if (poll) {
              clearInterval(poll);
              poll = undefined;
            }
          } else if (m.type === "error") {
            this.update({ error: m.data.message });
            if (m.data.code === "UNAUTHENTICATED")
              window.dispatchEvent(new Event("agentcity:session-expired"));
          }
        } catch {
          this.update({
            connection: "error",
            error:
              "Invalid stream data. Last valid state preserved; requesting a fresh snapshot.",
          });
          current.close();
          void fetchState();
        }
      };
      current.onclose = () => {
        if (!active()) return;
        ended = true;
        attempts++;
        this.update({ connection: attempts >= 3 ? "polling" : "reconnecting" });
        if (attempts >= 3 && !poll) poll = setInterval(fetchState, 2000);
        retry = setTimeout(
          connect,
          Math.min(10000, 1000 * 2 ** (attempts - 1)) + Math.random() * 300,
        );
      };
      current.onerror = () => {
        if (active()) current.close();
      };
    };
    connect();
    if (client.mode === "live")
      heartbeat = setInterval(() => {
        if (Date.now() - lastTraffic > 45000) socket?.close();
        else if (socket?.readyState === WebSocket.OPEN)
          socket.send(JSON.stringify({ type: "ping" }));
      }, 15000);
    return () => {
      closed = true;
      this.generation++;
      off?.();
      clearTimeout(retry);
      if (poll) clearInterval(poll);
      if (heartbeat) clearInterval(heartbeat);
      socket?.close();
    };
  }
}
