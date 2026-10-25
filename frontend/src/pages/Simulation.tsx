import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { Link, useNavigate, useParams, useBlocker } from "react-router-dom";
import {
  Activity,
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  Clock,
  FastForward,
  GitBranch,
  HelpCircle,
  History,
  Layers3,
  Maximize2,
  MessageSquare,
  Minus,
  Pause,
  Play,
  Plus,
  RotateCcw,
  RotateCw,
  Save,
  Search,
  Settings,
  SkipForward,
  Sparkles,
  Users,
  X,
  FileText,
  Info,
  SlidersHorizontal,
} from "lucide-react";
import { WorldStore } from "../state/world";
import { useApp, messageOf } from "../state/app";
import { ApiError } from "../api/client";
import type {
  CommandBody,
  Simulation as Sim,
  Speed,
  WorldFrame,
} from "../api/types";
import { colors, metricLabels, pretty, simTime } from "../api/defaults";
import World, { type CameraAction, type Overlay } from "../world/World";
import { Brand, Button, Busy, ErrorBox, Modal } from "../components/ui";
import { formatChord } from "../platform";
import Drawer, { type DrawerNode } from "../components/Drawer";
import ScenarioDialog, {
  InitialScenarioDialog,
  type ScenarioSource,
} from "../components/ScenarioDialog";
import LifeHUD from "../components/LifeHUD";
import OutcomeDialog from "../components/OutcomeDialog";
export default function Simulation() {
  const { id } = useParams();
  const { client, settings, capabilities, notice } = useApp();
  const navigate = useNavigate();
  const store = useMemo(() => new WorldStore(), [id]);
  const live = useSyncExternalStore(store.subscribe, store.getSnapshot);
  const [liveError, setLiveError] = useState("");
  const [stack, setStack] = useState<DrawerNode[]>([]),
    [menu, setMenu] = useState(false),
    [eventMenu, setEventMenu] = useState(false),
    [source, setSource] = useState<ScenarioSource | null>(null),
    [help, setHelp] = useState(false),
    [overlay, setOverlay] = useState<Overlay>(null),
    [hazards, setHazards] = useState(true),
    [follow, setFollow] = useState<string | null>(null),
    [fallback, setFallback] = useState(false),
    [busy, setBusy] = useState(false),
    [saveState, setSaveState] = useState("");
  const [focused, setFocused] = useState<string[]>([]);
  const [revision, setRevision] = useState<number | null>(null),
    [historical, setHistorical] = useState<WorldFrame | null>(null),
    [timeline, setTimeline] = useState<
      { ref: { tick: number; revision: number }; sim_time_seconds: number }[]
    >([]),
    [replaying, setReplaying] = useState(false),
    [replayRate, setReplayRate] = useState(1);
  const camera = useRef<(a: CameraAction) => void>(() => {}),
    latest = useRef<Sim | null>(null),
    commandPending = useRef(false),
    dragged = useRef(false),
    pointer = useRef({ x: 0, y: 0 });
  const pending = useRef<{ s: Sim; c: CommandBody; key: string } | null>(null);
  const seenEvents = useRef(new Set<string>()),
    restoreFocus = useRef<HTMLElement | null>(null);
  useEffect(() => store.start(id!, client), [id, client, store]);
  useEffect(() => {
    setStack([]);
    setRevision(null);
    setHistorical(null);
    setFollow(null);
    setFocused([]);
    setSource(null);
    setReplaying(false);
    seenEvents.current.clear();
  }, [id]);
  latest.current = live.frame?.simulation ?? null;
  const refresh = useCallback(async () => {
    const f = await client.state(id!);
    latest.current = f.simulation;
    store.accept(f);
  }, [client, id, store]);
  const execute = useCallback(
    async (c: CommandBody) => {
      if (commandPending.current)
        throw new ApiError(
          "COMMAND_PENDING",
          "Wait for the current operation to finish.",
        );
      if (
        revision !== null &&
        !(c.type === "save" && c.reason === "navigation")
      )
        throw new ApiError(
          "READ_ONLY",
          "Return to live before changing the city.",
        );
      const current = latest.current;
      if (!current) throw new Error("The city is still connecting.");
      commandPending.current = true;
      setBusy(true);
      setLiveError("");
      const prior = pending.current;
      const retry = prior && JSON.stringify(prior.c) === JSON.stringify(c);
      const operation = retry
        ? prior
        : { s: current, c, key: crypto.randomUUID() };
      pending.current = operation;
      try {
        await client.command(operation.s, c, operation.key);
        pending.current = null;
        await refresh();
      } catch (e) {
        setLiveError(messageOf(e));
        if (!(e instanceof ApiError) || !e.retryable) pending.current = null;
        throw e;
      } finally {
        commandPending.current = false;
        setBusy(false);
      }
    },
    [client, refresh, revision],
  );
  const navigationAllowed = useRef(false),
    savingBlockedNavigation = useRef(false);
  useEffect(() => {
    navigationAllowed.current = false;
    savingBlockedNavigation.current = false;
  }, [id]);
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      currentLocation.pathname !== nextLocation.pathname &&
      !navigationAllowed.current,
  );
  useEffect(() => {
    if (
      blocker.state !== "blocked" ||
      savingBlockedNavigation.current ||
      busy ||
      commandPending.current
    )
      return;
    savingBlockedNavigation.current = true;
    void execute({
      type: "save",
      reason: "navigation",
      label: "Saved before navigation",
    })
      .then(() => {
        navigationAllowed.current = true;
        notice("City paused and saved.");
        blocker.proceed();
      })
      .catch(() => {
        blocker.reset();
      })
      .finally(() => {
        savingBlockedNavigation.current = false;
      });
  }, [blocker, execute, notice, busy]);
  const cmd = (c: CommandBody) => {
    void execute(c).catch(() => {});
  };
  useEffect(() => {
    const leave = (e: BeforeUnloadEvent) => {
      if (commandPending.current) {
        e.preventDefault();
        e.returnValue = "A save is still pending.";
      }
    };
    window.addEventListener("beforeunload", leave);
    return () => window.removeEventListener("beforeunload", leave);
  }, []);
  useEffect(() => {
    const f = live.frame;
    if (!f) return;
    f.events.forEach((e) => {
      if (e.status === "active" && !seenEvents.current.has(e.id)) {
        seenEvents.current.add(e.id);
        notice(`${e.title} is now active.`);
      }
    });
    if (follow && !f.agents.some((a) => a.id === follow)) setFollow(null);
  }, [live.frame, follow, notice]);
  useEffect(() => {
    if (revision === null) {
      setHistorical(null);
      return;
    }
    let active = true;
    setFollow(null);
    setFocused([]);
    void client
      .state(id!, revision)
      .then((f) => {
        if (active) setHistorical(f);
      })
      .catch((e) => {
        if (active) setLiveError(messageOf(e));
      });
    return () => {
      active = false;
    };
  }, [client, id, revision]);
  useEffect(() => {
    if (!replaying || revision === null) return;
    const timer = setInterval(() => {
      setRevision((r) => {
        const index = timeline.findIndex((p) => p.ref.revision === r);
        if (index >= timeline.length - 1) {
          setReplaying(false);
          return r;
        }
        return timeline[index + 1].ref.revision;
      });
    }, 600 / replayRate);
    return () => clearInterval(timer);
  }, [replaying, timeline, revision, replayRate]);
  const dismiss = useCallback(() => {
    if (
      source ||
      help ||
      live.frame?.simulation.initial_preview ||
      live.frame?.simulation.pending_outcome_event_ids.length
    )
      return;
    if (menu) {
      setMenu(false);
      return;
    }
    if (stack.length) {
      setStack((s) => (s.length > 1 ? s.slice(0, -1) : []));
      restoreFocus.current?.focus();
    } else if (focused.length) {
      setFocused([]);
      setFollow(null);
      camera.current("reset");
    }
  }, [source, help, live.frame, menu, stack.length, focused.length]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") dismiss();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [dismiss]);
  const push = (n: DrawerNode) => {
    if (!stack.length)
      restoreFocus.current = document.activeElement as HTMLElement;
    setStack((s) => [...s, n]);
    setMenu(false);
  };
  const open = (n: DrawerNode) => {
    restoreFocus.current = document.activeElement as HTMLElement;
    setStack([n]);
    setMenu(false);
  };
  const onCameraReady = useCallback((action: (a: CameraAction) => void) => {
    camera.current = action;
  }, []);
  const unfollow = useCallback(() => setFollow(null), []);
  const onFallback = useCallback(() => {
    setFallback(true);
    notice("WebGL is unavailable. The interactive 2D map is active.");
  }, [notice]);
  const navigation = async (path: string) => {
    setMenu(false);
    try {
      setSaveState("Saving…");
      await execute({
        type: "save",
        reason: "navigation",
        label: "Saved before navigation",
      });
      setSaveState("Saved");
      notice("City paused and saved.");
      navigationAllowed.current = true;
      navigate(path, { state: { from: `/simulations/${id}` } });
    } catch {
      setSaveState("Save failed");
    }
  };
  const enterReplay = async () => {
    try {
      if (revision === null) await execute({ type: "pause" });
      const [allRevisions, snapshots] = await Promise.all([
        client.timeline(id!),
        client.snapshots(id!),
      ]);
      const firstReady = Math.min(
        ...snapshots
          .filter((s) => s.reason === "initial")
          .map((s) => s.ref.revision),
        latest.current!.revision,
      );
      // Initialization revisions are real progress records, but have no WorldFrame.
      const list = allRevisions.filter((p) => p.ref.revision >= firstReady);
      setTimeline(list);
      if (list.length) {
        setRevision(list[Math.max(0, list.length - 2)].ref.revision);
        setStack([]);
        setFollow(null);
      }
    } catch (e) {
      setLiveError(messageOf(e));
    }
  };
  const branch = async () => {
    if (revision === null) return;
    setBusy(true);
    try {
      const result = await client.branch(
        id!,
        `${latest.current?.name.slice(0, 55)} · alternate`,
        { kind: "revision", revision },
      );
      navigationAllowed.current = true;
      navigate(`/simulations/${result.simulation.id}`);
    } catch (e) {
      setLiveError(messageOf(e));
    } finally {
      setBusy(false);
    }
  };
  const frame = revision === null ? live.frame : historical;
  if (!frame)
    return (
      <div className="city-connecting">
        <Brand />
        <Busy
          text={
            revision === null
              ? "Connecting to your world…"
              : "Loading exact committed revision…"
          }
        />
        {(live.error || liveError) && (
          <ErrorBox
            error={live.error || liveError}
            retry={() =>
              void refresh().catch((e) => setLiveError(messageOf(e)))
            }
          />
        )}
        <Link className="back-link" to="/simulations">
          <ArrowLeft size={15} />
          Previous simulations
        </Link>
      </div>
    );
  const s = frame.simulation;
  const readOnly = revision !== null;
  const selected =
    focused[0] ??
    [...stack]
      .reverse()
      .find(
        (n): n is Extract<DrawerNode, { type: "agent" }> => n.type === "agent",
      )?.id ??
    null;
  const active = frame.events.filter(
    (e) => e.status === "active" || e.status === "queued",
  );
  const locked =
    busy ||
    !!source ||
    (!readOnly &&
      (!!s.initial_preview ||
        s.pending_outcome_event_ids.length > 0 ||
        s.archived ||
        s.status === "completed"));
  const eventLocked = locked || active.length > 0;
  const keydown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    if (
      target !== e.currentTarget &&
      target.tagName !== "CANVAS" &&
      target.tagName !== "svg"
    )
      return;
    if (
      source ||
      help ||
      s.initial_preview ||
      s.pending_outcome_event_ids.length
    )
      return;
    const chord = [
      e.metaKey || e.ctrlKey ? "Mod" : null,
      e.altKey ? "Alt" : null,
      e.shiftKey ? "Shift" : null,
      e.code,
    ]
      .filter(Boolean)
      .join("+");
    const match = Object.entries(settings.shortcuts).find(
      ([, v]) => v === chord,
    )?.[0] as keyof typeof settings.shortcuts | undefined;
    const action = chord === "Mod+Shift+Equal" ? "zoom_in" : match;
    if (!action) return;
    e.preventDefault();
    if (action === "pause") {
      if (!locked) {
        if (readOnly) setReplaying((v) => !v);
        else cmd({ type: s.status === "running" ? "pause" : "play" });
      }
    } else camera.current(action);
  };
  return (
    <div
      className={`simulation-page life-mode ${focused.length ? "life-focused" : ""} ${stack.length ? "drawer-open" : ""}`}
    >
      <div
        className="world-wrap"
        tabIndex={0}
        role="region"
        aria-label="City viewport. Space toggles play. Arrow keys pan. Press help for more shortcuts."
        onKeyDown={keydown}
        onPointerDown={(e) => {
          pointer.current = { x: e.clientX, y: e.clientY };
          dragged.current = false;
        }}
        onPointerMove={(e) => {
          if (
            Math.hypot(
              e.clientX - pointer.current.x,
              e.clientY - pointer.current.y,
            ) > 5
          )
            dragged.current = true;
        }}
      >
        <World
          frame={frame}
          mode={fallback ? "2d" : settings.view_mode}
          selected={selected}
          focus={focused}
          onSelect={(agentId) => {
            setMenu(false);
            setStack([]);
            setFocused([agentId]);
            setFollow(agentId);
          }}
          onEmpty={() => {
            if (!dragged.current) {
              setMenu(false);
              setStack([]);
            }
          }}
          overlay={overlay}
          hazards={hazards}
          follow={follow}
          onUnfollow={unfollow}
          reducedMotion={settings.reduce_motion}
          theme={settings.theme}
          onCameraReady={onCameraReady}
          onFallback={onFallback}
        />
      </div>
      <div className="world-vignette" />
      {import.meta.env.DEV &&
        new URLSearchParams(window.location.search).has("qa") &&
        !fallback && (
          <button
            className="qa-loss"
            onClick={() => {
              const canvas =
                document.querySelector<HTMLCanvasElement>(".world-wrap canvas");
              const gl = canvas?.getContext("webgl2");
              if (gl) gl.getExtension("WEBGL_lose_context")?.loseContext();
              else onFallback();
            }}
          >
            Test WebGL fallback
          </button>
        )}

      <div className="city-brand-wrap">
        <div className="city-brand glass">
          <button
            className="brand-button"
            aria-label="Open city menu"
            aria-expanded={menu}
            onClick={() => setMenu((v) => !v)}
          >
            <Brand />
          </button>
          <button
            className="icon-button"
            aria-label="Toggle city menu"
            aria-expanded={menu}
            onClick={() => setMenu((v) => !v)}
          >
            <ChevronDown size={15} />
          </button>
        </div>
        <div className="city-name">
          <span>{s.name}</span>
          <span className="pill">{pretty(s.config.mode)}</span>
        </div>
        {menu && (
          <div className="logo-menu glass">
            <div className="menu-world">
              <span>YOUR WORLD</span>
              <strong>{s.name}</strong>
            </div>
            <button
              onClick={() => setEventMenu((v) => !v)}
              disabled={readOnly || eventLocked}
            >
              <Sparkles size={16} />
              Add event
              <ChevronRight size={15} />
            </button>
            {eventMenu && (
              <div className="event-submenu">
                {(
                  [
                    "random",
                    "repeat",
                    "custom",
                    ...(s.config.mode === "policy_lab" ? ["policy"] : []),
                  ] as ScenarioSource[]
                ).map((type) => (
                  <button
                    key={type}
                    disabled={
                      locked ||
                      readOnly ||
                      (type === "repeat" &&
                        !frame.events.some((e) => e.status === "resolved"))
                    }
                    title={
                      type === "repeat" &&
                      !frame.events.some((e) => e.status === "resolved")
                        ? "No resolved events to repeat yet"
                        : undefined
                    }
                    onClick={() => {
                      setSource(type);
                      setMenu(false);
                    }}
                  >
                    {pretty(type)} event
                  </button>
                ))}
                {!frame.events.some((e) => e.status === "resolved") && (
                  <small>Repeat needs a resolved event.</small>
                )}
              </div>
            )}
            <button
              onClick={() => void navigation("/simulations/new")}
              disabled={busy}
            >
              <Plus size={16} />
              Create new
            </button>
            <button
              onClick={() => void navigation("/simulations")}
              disabled={busy}
            >
              <History size={16} />
              Previous simulations
            </button>
            <hr />
            <button onClick={() => open({ type: "events" })}>
              <FileText size={16} />
              Event logs
            </button>
            <button onClick={() => open({ type: "overview" })}>
              <Activity size={16} />
              Simulation overview
            </button>
            <button
              onClick={() => open({ type: "agents" })}
              disabled={
                readOnly ||
                frame.agents.length >= (capabilities?.max_agents ?? 100)
              }
              title={
                frame.agents.length >= (capabilities?.max_agents ?? 100)
                  ? "This city is at its citizen limit"
                  : undefined
              }
            >
              <Users size={16} />
              Add agent
            </button>
            <button onClick={() => open({ type: "search" })}>
              <Search size={16} />
              Search agent
            </button>
            <button onClick={() => open({ type: "overlays" })}>
              <Layers3 size={16} />
              World overlays
            </button>
            <button onClick={() => open({ type: "compare" })}>
              <GitBranch size={16} />
              Compare timelines
            </button>
            <hr />
            <button onClick={() => void navigation("/settings")}>
              <Settings size={16} />
              Settings
            </button>
            <button onClick={() => void navigation("/about")}>
              <Info size={16} />
              About
            </button>
            <button onClick={() => void navigation("/")}>
              <ArrowLeft size={16} />
              Return home
            </button>
          </div>
        )}
      </div>
      <div className="transport-wrap">
        <div className="transport-bar glass">
          <div className="sim-clock">
            <Clock size={16} />
            <span>{simTime(s.sim_time_seconds)}</span>
          </div>
          <div className="transport-divider" />
          <button
            className="icon-button"
            onClick={() => void enterReplay()}
            disabled={busy || !!source}
            aria-label="Rewind recorded history"
          >
            <History size={18} />
          </button>
          <button
            className={`play-button ${s.status === "running" && !readOnly ? "playing" : ""}`}
            aria-label={
              readOnly
                ? replaying
                  ? "Pause replay"
                  : "Play replay"
                : s.status === "running"
                  ? "Pause simulation"
                  : "Play simulation"
            }
            disabled={locked}
            onClick={() =>
              readOnly
                ? setReplaying((v) => !v)
                : cmd({ type: s.status === "running" ? "pause" : "play" })
            }
          >
            {readOnly ? (
              replaying ? (
                <Pause size={18} />
              ) : (
                <Play size={18} />
              )
            ) : s.status === "running" ? (
              <Pause size={18} />
            ) : (
              <Play size={18} />
            )}
          </button>
          <button
            className="icon-button"
            disabled={locked || (!readOnly && s.status === "running")}
            aria-label="Step one tick"
            onClick={() => {
              if (readOnly) {
                const index = timeline.findIndex(
                  (p) => p.ref.revision === revision,
                );
                if (timeline[index + 1])
                  setRevision(timeline[index + 1].ref.revision);
              } else cmd({ type: "step", count: 1 });
            }}
          >
            <SkipForward size={18} />
          </button>
          <div className="transport-divider" />
          <select
            aria-label={readOnly ? "Replay speed" : "Simulation speed"}
            value={readOnly ? replayRate : s.speed_multiplier}
            disabled={locked}
            onChange={(e) =>
              readOnly
                ? setReplayRate(Number(e.target.value))
                : cmd({
                    type: "set_speed",
                    value: Number(e.target.value) as Speed,
                  })
            }
          >
            {[0.25, 0.5, 1, 2, 5, 10].map((speed) => (
              <option key={speed} value={speed}>
                {speed}×
              </option>
            ))}
          </select>
          <button
            className="icon-button"
            aria-label="Fast forward"
            disabled={locked}
            onClick={() =>
              readOnly
                ? setReplayRate(5)
                : cmd({ type: "set_speed", value: 10 })
            }
          >
            <FastForward size={17} />
          </button>
          <div className="transport-divider" />
          <span
            className={`connection ${readOnly ? "replay" : live.connection}`}
          >
            <i />
            {readOnly
              ? "REPLAY"
              : client.mode === "mock"
                ? "MOCK"
                : live.connection === "live"
                  ? "LIVE"
                  : live.connection.toUpperCase()}
          </span>
        </div>
        <span
          className="pill engine-mode"
          aria-label="Decision engine"
          title="Each citizen decision records whether it came from Gemini or deterministic rules."
        >
          {client.mode === "mock"
            ? "Recorded fixtures"
            : capabilities?.gemini
              ? "Gemini + rules"
              : "Rules engine"}
        </span>
        <div className="quick-stats glass">
          {(Object.keys(metricLabels) as (keyof typeof metricLabels)[]).map(
            (k) => (
              <button
                key={k}
                onClick={() => open({ type: "overview" })}
                aria-label={`${metricLabels[k]} ${frame.metrics.values[k].toFixed(0)} of 100, view reasons`}
              >
                <span>
                  <i style={{ background: colors[k] }} />
                  {metricLabels[k]}
                </span>
                <strong>
                  {frame.metrics.values[k].toFixed(0)}
                  <small>%</small>
                </strong>
              </button>
            ),
          )}
        </div>
        <div className={`event-notice ${active.length ? "has-event" : ""}`}>
          <span className="status-dot" />
          {active.length ? (
            <button onClick={() => open({ type: "event", id: active[0].id })}>
              {active[0].title}{" "}
              <span>
                {active[0].status === "queued"
                  ? "Queued until Play"
                  : `${active.length} active event`}
              </span>
              <ChevronRight size={13} />
            </button>
          ) : (
            <span>No major events occurring</span>
          )}
        </div>
      </div>
      <div className="city-top-right">
        <button
          className="icon-button glass"
          aria-label="Find a citizen"
          onClick={() => open({ type: "search" })}
        >
          <Search size={19} />
        </button>
        <button
          className="icon-button glass"
          aria-label="World overlays"
          onClick={() => open({ type: "overlays" })}
        >
          <SlidersHorizontal size={19} />
        </button>
        <button
          className="icon-button glass"
          aria-label="Keyboard shortcut help"
          onClick={() => setHelp(true)}
        >
          <HelpCircle size={19} />
        </button>
      </div>
      {(liveError || live.error) && (
        <div className="city-error">
          <span role="alert">{liveError || live.error}</span>
          <button
            onClick={() => {
              setLiveError("");
              store.update({ error: null });
            }}
            aria-label="Dismiss error"
          >
            <X size={16} />
          </button>
        </div>
      )}
      {readOnly && (
        <div className="replay-bar glass">
          <div>
            <History size={18} />
            <span>
              Historical playback{" "}
              <small>
                Read only · Revision {frame.ref.revision}
                {historical?.ref.revision !== revision
                  ? " · loading selection…"
                  : ""}
              </small>
            </span>
          </div>
          <input
            aria-label="Committed history revision"
            type="range"
            min={0}
            max={Math.max(0, timeline.length - 1)}
            value={Math.max(
              0,
              timeline.findIndex((p) => p.ref.revision === revision),
            )}
            onChange={(e) => {
              setReplaying(false);
              setRevision(timeline[Number(e.target.value)].ref.revision);
            }}
          />
          <Button
            kind="secondary"
            onClick={() => {
              setRevision(null);
              setReplaying(false);
              setStack([]);
            }}
          >
            Return to live
          </Button>
          <Button
            disabled={busy || frame.ref.tick >= s.config.max_ticks}
            onClick={() => void branch()}
          >
            <GitBranch size={15} />
            Continue from here
          </Button>
        </div>
      )}
      <div className="world-caption">
        <span className="eyebrow">{readOnly ? "Replay" : "Live"}</span>
        <h1>{s.name}</h1>
        <p>
          {readOnly
            ? "Viewing a recorded revision. Branch from it to try another outcome."
            : s.status === "running"
              ? "Simulation running. Zoom in to read conversations."
              : "Simulation paused. Press Play to continue."}
        </p>
      </div>
      <div className="city-bottom-left">
        <Button
          kind="primary"
          disabled={readOnly || eventLocked}
          onClick={() => setSource("custom")}
        >
          <Sparkles size={17} />
          Introduce an event
          <Plus size={16} />
        </Button>
        <button
          className="glass quiet-button"
          onClick={() => open({ type: "feed" })}
        >
          <MessageSquare size={17} />
          Conversations
          <span>
            {new Set(frame.recent_dialogue.map((d) => d.interaction_id)).size}
          </span>
        </button>
        <button
          className="glass quiet-button"
          onClick={() => open({ type: "traits" })}
        >
          <Users size={17} />
          Agent traits<span>{frame.agents.length}</span>
        </button>
      </div>
      <div className="camera-tools glass">
        <button
          className="icon-button"
          aria-label="Zoom in"
          onClick={() => camera.current("zoom_in")}
        >
          <Plus size={18} />
        </button>
        <button
          className="icon-button"
          aria-label="Zoom out"
          onClick={() => camera.current("zoom_out")}
        >
          <Minus size={18} />
        </button>
        <hr />
        <button
          className="icon-button"
          aria-label="Rotate left"
          disabled={settings.view_mode === "2d" || fallback}
          onClick={() => camera.current("rotate_left")}
        >
          <RotateCcw size={17} />
        </button>
        <button
          className="icon-button"
          aria-label="Rotate right"
          disabled={settings.view_mode === "2d" || fallback}
          onClick={() => camera.current("rotate_right")}
        >
          <RotateCw size={17} />
        </button>
        <button
          className="icon-button"
          aria-label="Reset camera"
          onClick={() => {
            setFollow(null);
            setFocused([]);
            camera.current("reset");
          }}
        >
          <Maximize2 size={17} />
        </button>
      </div>
      {!source && !help && (
        <LifeHUD
          frame={frame}
          focused={focused}
          onFocus={(ids) => {
            setFocused(ids);
            setFollow(ids[0] ?? null);
            setStack([]);
            setMenu(false);
          }}
          onClose={() => {
            setFocused([]);
            setFollow(null);
            camera.current("reset");
          }}
          onProfile={(agentId) => open({ type: "agent", id: agentId })}
          onCommand={execute}
          locked={locked}
          readOnly={readOnly}
        />
      )}
      <div className="city-footer">
        <span>
          <Users size={13} />
          {s.agent_count} citizens<span className="footer-dot">·</span>
          {settings.view_mode === "2d" || fallback ? "2D MAP" : "3D WORLD"}
          {follow && (
            <span className="positive">Following citizen · pan to stop</span>
          )}
        </span>
        <span>
          {s.status === "running"
            ? `${s.achieved_ticks_per_second.toFixed(1)} ticks/s achieved · `
            : ""}
          Tick {frame.ref.tick}
          <span className="footer-dot">·</span>Rev {frame.ref.revision}
          <span className="footer-dot">·</span>
          <button
            disabled={busy || readOnly}
            onClick={() => {
              setSaveState("Saving…");
              void execute({
                type: "save",
                reason: "manual",
                label: "Manual save",
              })
                .then(() => setSaveState("Saved"))
                .catch(() => setSaveState("Save failed"));
            }}
          >
            <Save size={12} />
            {saveState || "Save city"}
          </button>
        </span>
      </div>
      {overlay && (
        <div className="map-legend glass">
          <span>
            {overlay === "density"
              ? "Population / km²"
              : `${metricLabels[overlay]} /100`}
          </span>
          <div className="legend-gradient" />
          <small>
            0 <span>{overlay === "density" ? "10,000+" : "100"}</span>
          </small>
        </div>
      )}
      {stack.length > 0 && (
        <Drawer
          onWatch={(ids) => {
            setFocused(ids);
            setFollow(ids[0] ?? null);
            setStack([]);
          }}
          readOnly={readOnly}
          stack={stack}
          frame={frame}
          revision={frame.ref.revision}
          onPush={push}
          onBack={() => {
            setStack((s) => s.slice(0, -1));
            if (stack.length === 1) restoreFocus.current?.focus();
          }}
          onClose={() => {
            setStack([]);
            restoreFocus.current?.focus();
          }}
          onCommand={execute}
          overlay={overlay}
          setOverlay={setOverlay}
          hazards={hazards}
          setHazards={setHazards}
          follow={follow}
          setFollow={setFollow}
        />
      )}
      {source && (
        <ScenarioDialog
          key={`${id}-${source}`}
          simulation={live.frame!.simulation}
          map={live.frame!.map}
          source={source}
          onClose={() => setSource(null)}
          onUpdated={refresh}
        />
      )}
      {!source && !readOnly && s.initial_preview && (
        <InitialScenarioDialog
          simulation={s}
          map={frame.map}
          onUpdated={refresh}
        />
      )}
      {!source && !readOnly && s.pending_outcome_event_ids[0] && (
        <OutcomeDialog
          key={s.pending_outcome_event_ids[0]}
          simulation={s}
          eventId={s.pending_outcome_event_ids[0]}
          onUpdated={refresh}
        />
      )}
      {help && (
        <Modal
          title="Keyboard shortcuts"
          onClose={() => setHelp(false)}
        >
          <p className="muted">
            Shortcuts apply when the map has keyboard focus. Click an empty part
            of the map first.
          </p>
          <div className="shortcut-list">
            {Object.entries(settings.shortcuts).map(([k, v]) => (
              <div key={k}>
                <span>{pretty(k)}</span>
                <kbd>{formatChord(v)}</kbd>
              </div>
            ))}
          </div>
          <p className="helper-text">
            Drag to orbit. Right-drag to pan. Use the visible camera buttons for
            the same controls. Escape closes the topmost menu or panel. Change
            shortcuts in Settings.
          </p>
          <Button onClick={() => setHelp(false)}>Got it</Button>
        </Modal>
      )}
    </div>
  );
}
