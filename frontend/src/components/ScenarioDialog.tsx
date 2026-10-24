import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  Users,
  Building2,
  Clock,
  MapPin,
} from "lucide-react";
import { useApp, messageOf, useQuery } from "../state/app";
import { Button, Modal, Busy, ErrorBox, Field, Empty } from "./ui";
import { ApiError } from "../api/client";
import type {
  Intervention,
  ScenarioPreview,
  Simulation,
  Policies,
  EffectSpec,
} from "../api/types";
import { pretty } from "../api/defaults";
import { ScenarioDiorama } from "../world/ScenarioScene";
import {
  previewLayout,
  previewPoint,
  type MapBounds,
} from "../world/previewGeometry";
function describeEffect(effect: EffectSpec): string {
  switch (effect.type) {
    case "wellbeing":
      return (
        [
          effect.happiness_delta
            ? `Happiness ${effect.happiness_delta > 0 ? "+" : ""}${effect.happiness_delta}`
            : "",
          effect.stress_delta
            ? `stress ${effect.stress_delta > 0 ? "+" : ""}${effect.stress_delta}`
            : "",
          effect.health_delta
            ? `health ${effect.health_delta > 0 ? "+" : ""}${effect.health_delta}`
            : "",
        ]
          .filter(Boolean)
          .join(", ") + " per tick for citizens in the area."
      );
    case "information":
      return effect.reliability === 100
        ? "Citizens learn about your event, remember it, and can talk about it with one another."
        : `Word spreads: “${effect.message}”`;
    case "hazard":
      return `${pretty(effect.hazard)} affects the highlighted area. Citizens can seek safety or help each other.`;
    case "community":
      return effect.activity === "festival"
        ? "A gathering lifts happiness and gives neighbors a break from stress."
        : "Community aid provides supplies to citizens in the area.";
    case "infrastructure":
      return effect.functional
        ? `Local buildings operate at ${Math.round(effect.capacity_multiplier * 100)}% capacity.`
        : "Local buildings close until the event ends.";
    case "resource_multiplier":
      return `${pretty(effect.resource)} stocks change to ${Math.round(effect.multiplier * 100)}% of their current amount.`;
    case "policy":
      return `Aid runs at ${Math.round(effect.aid_multiplier * 100)}%${effect.evacuation_order ? ", with an evacuation order" : ""}${effect.ration_units_per_agent !== null ? ` and ${effect.ration_units_per_agent} units per citizen` : ""}.`;
  }
}
export type ScenarioSource = "random" | "repeat" | "custom" | "policy";
export function PreviewCard({
  preview,
  map,
}: {
  preview: ScenarioPreview;
  map: MapBounds;
}) {
  const layout = previewLayout(map);
  const origin = previewPoint(preview.spec.origin, map);
  return (
    <div className="preview-card">
      <div className="preview-title">
        <Sparkles size={19} />
        <span>INTERPRETED SCENARIO</span>
      </div>
      <h3>{preview.spec.title}</h3>
      <p>{preview.interpretation}</p>
      <ScenarioDiorama objects={preview.spec.scene ?? []} />
      {!!preview.spec.scene?.length && (
        <div className="scenario-prop-list">
          {[...new Set(preview.spec.scene.map((o) => o.model))].map((model) => (
            <span key={model}>
              {model === "generated"
                ? preview.spec.scene?.find((o) => o.model === model)?.label
                : pretty(model)}
            </span>
          ))}
        </div>
      )}
      <svg
        viewBox="0 0 280 85"
        className="preview-map"
        role="img"
        aria-label="Planned affected region on the city map"
      >
        <defs>
          <pattern
            id="preview-grid"
            width="15"
            height="15"
            patternUnits="userSpaceOnUse"
          >
            <path
              d="M15 0H0V15"
              stroke="currentColor"
              opacity=".18"
              fill="none"
            />
          </pattern>
        </defs>
        <rect width="280" height="85" fill="url(#preview-grid)" />
        <rect
          x={layout.x}
          y={layout.y}
          width={map.width_m * layout.scale}
          height={map.height_m * layout.scale}
          fill="none"
          stroke="currentColor"
          opacity=".4"
        />
        <polygon
          points={preview.spec.affected_polygon
            .map((p) => {
              const point = previewPoint(p, map);
              return `${point.x},${point.y}`;
            })
            .join(" ")}
          fill="#a58ce7"
          fillOpacity=".2"
          stroke="#bfa1ff"
        />
        <circle cx={origin.x} cy={origin.y} r="3" fill="#a9f4de" />
      </svg>
      <div className="preview-facts">
        <span>
          <Users size={15} />
          {preview.affected_agent_ids.length} citizens
        </span>
        <span>
          <Building2 size={15} />
          {preview.affected_building_ids.length} buildings
        </span>
        <span>
          <Clock size={15} />
          {preview.spec.duration_ticks} ticks
        </span>
        <span>
          <MapPin size={15} />
          Severity {preview.spec.severity}/100
        </span>
      </div>
      <div className="supported-effects">
        <h4>What happens in your city</h4>
        {preview.spec.effects.map((effect, i) => (
          <p className="event-effect" key={i}>
            <Check size={14} />
            {describeEffect(effect)}
          </p>
        ))}
      </div>
      {preview.warnings.map((w, i) => (
        <p className="helper-text" key={i}>
          {w}
        </p>
      ))}
      {preview.unsupported_requests.length > 0 && (
        <div className="warning">
          <ShieldAlert size={18} />
          <div>
            <strong>Unsupported parts</strong>
            {preview.unsupported_requests.map((u, i) => (
              <p key={i}>{u}</p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
export default function ScenarioDialog({
  simulation,
  map,
  source,
  onClose,
  onUpdated,
}: {
  simulation: Simulation;
  map: MapBounds;
  source: ScenarioSource;
  onClose: () => void;
  onUpdated: () => Promise<void>;
}) {
  const { client, notice } = useApp();
  const [intervention, setIntervention] = useState<Intervention | null>(null),
    [preview, setPreview] = useState<ScenarioPreview | null>(null),
    [prompt, setPrompt] = useState(""),
    [eventId, setEventId] = useState(""),
    [busy, setBusy] = useState(true),
    [error, setError] = useState(""),
    [examples, setExamples] = useState(0);
  const [policy, setPolicy] = useState<Policies>({
    evacuation_order: false,
    ration_units_per_agent: null,
    aid_multiplier: 1,
  });
  const openKey = useRef(crypto.randomUUID()),
    commitKey = useRef(crypto.randomUUID()),
    previewKey = useRef(crypto.randomUUID()),
    cancelKey = useRef(crypto.randomUUID());
  const started = useRef(false);
  const openingError = useRef<unknown>(null);
  const events = useQuery(
    () => client.events(simulation.id, simulation.revision),
    [simulation.id],
  );
  const resolved = events.data?.filter((e) => e.status === "resolved") ?? [];
  const enter = async () => {
    setBusy(true);
    setError("");
    try {
      const i = await client.intervene(simulation, openKey.current);
      setIntervention(i);
      await onUpdated();
      if (source === "random") {
        const p = await client.preview(
          simulation.id,
          {
            intervention_id: i.id,
            source,
            source_event_id: null,
            prompt: null,
            policy: null,
          },
          previewKey.current,
        );
        setPreview(p);
      }
    } catch (e) {
      openingError.current = e;
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    if (!started.current) {
      started.current = true;
      void enter();
    }
  }, []);
  const cancel = async () => {
    if (busy) return;
    if (!intervention) {
      if (
        openingError.current instanceof ApiError &&
        openingError.current.retryable
      ) {
        setBusy(true);
        setError("");
        try {
          const recovered = await client.intervene(simulation, openKey.current);
          setIntervention(recovered);
          await client.cancel(simulation.id, recovered, cancelKey.current);
          await onUpdated();
          onClose();
        } catch (e) {
          setError(messageOf(e));
          setBusy(false);
        }
        return;
      }
      onClose();
      return;
    }
    setBusy(true);
    setError("");
    try {
      await client.cancel(simulation.id, intervention, cancelKey.current);
      await onUpdated();
      onClose();
    } catch (e) {
      try {
        if (
          e instanceof ApiError &&
          ["PREVIEW_EXPIRED", "PREVIEW_STALE", "NOT_FOUND"].includes(e.code)
        ) {
          await onUpdated();
          notice(
            "This event editor is no longer active. The current playback state is preserved.",
          );
          onClose();
          return;
        }
        if (e instanceof ApiError && e.code === "CONTROL_CONFLICT") {
          const current = await client.simulation(simulation.id);
          setIntervention({
            ...intervention,
            control_version: current.control_version,
          });
          cancelKey.current = crypto.randomUUID();
        }
        setError(messageOf(e));
      } catch (refreshError) {
        setError(messageOf(refreshError));
      } finally {
        setBusy(false);
      }
    }
  };
  const requestPreview = async () => {
    if (!intervention) return;
    setBusy(true);
    setError("");
    try {
      const p = await client.preview(
        simulation.id,
        {
          intervention_id: intervention.id,
          source,
          source_event_id: source === "repeat" ? eventId : null,
          prompt: source === "custom" ? prompt : null,
          policy: source === "policy" ? policy : null,
        },
        previewKey.current,
      );
      setPreview(p);
      commitKey.current = crypto.randomUUID();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  };
  const commit = async () => {
    if (!preview || !intervention) return;
    setBusy(true);
    setError("");
    try {
      const result = await client.commit(
        simulation.id,
        intervention,
        preview,
        commitKey.current,
      );
      await onUpdated();
      notice(
        result.simulation.status === "paused"
          ? "Event queued. Event will begin once you press Play."
          : "Event introduced. The city is running.",
      );
      onClose();
    } catch (e) {
      try {
        if (
          e instanceof ApiError &&
          ["CONTROL_CONFLICT", "PREVIEW_STALE"].includes(e.code)
        ) {
          const current = await client.simulation(simulation.id);
          setIntervention({
            ...intervention,
            control_version: current.control_version,
          });
          setPreview(null);
          previewKey.current = crypto.randomUUID();
          commitKey.current = crypto.randomUUID();
        }
        setError(messageOf(e));
      } catch (refreshError) {
        setError(messageOf(refreshError));
      } finally {
        setBusy(false);
      }
    }
  };
  const edit = () => {
    setPreview(null);
    previewKey.current = crypto.randomUUID();
  };
  const suggestions = [
    [
      "Dinosaurs appear in the town square for 20 ticks.",
      "An alien spacecraft arrives during a neighborhood festival.",
      "A farmers market and community garden open in the east.",
    ],
    [
      "A snowstorm arrives while robots deliver community aid.",
      "A medical clinic opens during a water shortage.",
      "A mysterious portal brings visitors into the city.",
    ],
    [
      "A peaceful protest starts beside a construction site.",
      "Deer wander through a concert in the neighborhood.",
      "A meteor reveals an ancient artifact.",
    ],
  ][examples % 3];
  return (
    <Modal
      title={
        source === "random"
          ? "Trigger a random event"
          : source === "repeat"
            ? "Trigger a repeated event"
            : source === "policy"
              ? "Apply a policy"
              : "Trigger a custom event"
      }
      eyebrow={intervention ? "Simulation paused" : "Waiting for a safe pause"}
      onClose={() => void cancel()}
      busy={busy}
    >
      {busy && !intervention ? (
        <Busy text="Waiting for the city to pause safely…" />
      ) : !intervention ? (
        <>
          <ErrorBox error={error} />
          <Button onClick={() => void enter()}>Retry safe pause</Button>
        </>
      ) : (
        <>
          <p className="dialog-intro">
            {source === "custom"
              ? "Describe the event you want to add. Nothing changes until you confirm."
              : source === "random"
                ? "Here is a randomly chosen event. Nothing changes until you confirm."
                : "Review the planned effects before anything changes."}
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (!busy) void requestPreview();
            }}
          >
            {source === "custom" && (
              <>
                <Field label="Describe your event">
                  <textarea
                    autoFocus
                    rows={4}
                    maxLength={2000}
                    value={prompt}
                    placeholder="What if…"
                    onChange={(e) => {
                      setPrompt(e.target.value);
                      edit();
                    }}
                    disabled={busy}
                  />
                </Field>
                <div className="example-heading">
                  <span>NEED A SPARK?</span>
                  <button
                    className="text-button"
                    type="button"
                    onClick={() => setExamples((n) => n + 1)}
                  >
                    <RefreshCw size={13} /> New ideas
                  </button>
                </div>
                <div className="event-examples">
                  {suggestions.map((s) => (
                    <button
                      type="button"
                      key={s}
                      onClick={() => {
                        setPrompt(s);
                        edit();
                      }}
                    >
                      {s}
                      <ArrowRight size={13} />
                    </button>
                  ))}
                </div>
              </>
            )}
            {source === "repeat" &&
              (resolved.length ? (
                <Field label="Resolved event">
                  <select
                    value={eventId}
                    disabled={busy}
                    onChange={(e) => {
                      setEventId(e.target.value);
                      edit();
                    }}
                  >
                    <option value="">Choose a previous event</option>
                    {resolved.map((e) => (
                      <option key={e.id} value={e.id}>
                        {e.title}
                      </option>
                    ))}
                  </select>
                </Field>
              ) : (
                <Empty title="No events to repeat yet">
                  Resolve a major event in this city first.
                </Empty>
              ))}
            {source === "policy" && (
              <div className="policy-fields">
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={policy.evacuation_order}
                    onChange={(e) => {
                      setPolicy((p) => ({
                        ...p,
                        evacuation_order: e.target.checked,
                      }));
                      edit();
                    }}
                  />{" "}
                  Broadcast evacuation order
                </label>
                <Field label="Aid multiplier (0–3)">
                  <input
                    type="number"
                    min={0}
                    max={3}
                    step={0.1}
                    value={policy.aid_multiplier}
                    onChange={(e) => {
                      setPolicy((p) => ({
                        ...p,
                        aid_multiplier: Number(e.target.value),
                      }));
                      edit();
                    }}
                  />
                </Field>
                <Field label="Ration units per citizen (blank for none)">
                  <input
                    type="number"
                    min={0}
                    value={policy.ration_units_per_agent ?? ""}
                    onChange={(e) => {
                      setPolicy((p) => ({
                        ...p,
                        ration_units_per_agent:
                          e.target.value === "" ? null : Number(e.target.value),
                      }));
                      edit();
                    }}
                  />
                </Field>
              </div>
            )}
            {preview && <PreviewCard preview={preview} map={map} />}{" "}
            {error && intervention && <ErrorBox error={error} />}
            <div className="modal-actions">
              <Button
                kind="ghost"
                disabled={busy}
                onClick={() => void cancel()}
              >
                Cancel
              </Button>
              {preview ? (
                <Button
                  disabled={busy || !preview.can_commit}
                  onClick={() => void commit()}
                >
                  {busy ? "Confirming…" : "Confirm event"}
                  <Check size={16} />
                </Button>
              ) : (
                <Button
                  type="submit"
                  disabled={
                    busy ||
                    (source === "custom" && !prompt.trim()) ||
                    (source === "repeat" && !eventId)
                  }
                >
                  {busy ? "Preparing preview…" : "Preview event"}
                  <ArrowRight size={16} />
                </Button>
              )}
            </div>
          </form>
        </>
      )}
    </Modal>
  );
}
export function InitialScenarioDialog({
  simulation,
  map,
  onUpdated,
}: {
  simulation: Simulation;
  map: MapBounds;
  onUpdated: () => Promise<void>;
}) {
  const { client, notice } = useApp();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const confirmKey = useRef(crypto.randomUUID()),
    skipKey = useRef(crypto.randomUUID());
  const decide = async (decision: "confirm" | "skip") => {
    setBusy(true);
    try {
      await client.initial(
        simulation,
        decision,
        decision === "confirm" ? confirmKey.current : skipKey.current,
      );
      await onUpdated();
      notice(
        decision === "confirm"
          ? "Event queued. Event will begin once you press Play."
          : "Opening scenario skipped. Your city is ready to explore.",
      );
    } catch (e) {
      setError(messageOf(e));
      setBusy(false);
    }
  };
  return (
    <Modal
      title="Review the opening scenario"
      onClose={() => void decide("skip")}
      busy={busy}
    >
      <PreviewCard preview={simulation.initial_preview!} map={map} />
      {error && <ErrorBox error={error} />}
      <div className="modal-actions">
        <Button
          kind="ghost"
          disabled={busy}
          onClick={() => void decide("skip")}
        >
          Skip scenario
        </Button>
        <Button
          disabled={busy || !simulation.initial_preview?.can_commit}
          onClick={() => void decide("confirm")}
        >
          Confirm opening event
          <Check size={16} />
        </Button>
      </div>
    </Modal>
  );
}
