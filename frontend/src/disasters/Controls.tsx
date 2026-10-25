import type { DisasterParameters } from "./client";
import { limits } from "./client";
import type { Vec2 } from "../api/types";
import "./disasters.css";

export default function DisasterControls({
  value,
  width,
  height,
  cell,
  tickSeconds,
  onChange,
  footprint,
  disabled = false,
}: {
  disabled?: boolean;
  value: DisasterParameters;
  width: number;
  height: number;
  cell: number;
  tickSeconds: number;
  onChange: (v: DisasterParameters) => void;
  footprint?: Vec2[];
}) {
  const limit = limits[value.kind];
  const set = (patch: Partial<DisasterParameters>) =>
    onChange({ ...value, ...patch });
  const numeric = (
    label: string,
    field: "intensity" | "extent_m" | "duration_ticks",
    min: number,
    max: number,
    step: number,
  ) => (
    <div className="disaster-control">
      <label htmlFor={`disaster-${field}`}>{label}</label>
      <div>
        <input
          id={`disaster-${field}`}
          aria-label={label}
          type="range"
          min={min}
          max={max}
          step={step}
          value={Number.isFinite(value[field]) ? value[field] : min}
          onChange={(e) => set({ [field]: Number(e.target.value) })}
        />
        <input
          aria-label={`${label} value`}
          type="number"
          min={min}
          max={max}
          step={step}
          value={Number.isFinite(value[field]) ? value[field] : ""}
          onChange={(e) =>
            set({
              [field]: e.target.value === "" ? NaN : Number(e.target.value),
            })
          }
          required
        />
      </div>
    </div>
  );
  return (
    <fieldset className="disaster-controls" disabled={disabled}>
      <legend>Physical disaster controls</legend>
      {numeric(
        `${limit.label} (${limit.unit})`,
        "intensity",
        limit.min,
        limit.max,
        limit.step,
      )}
      <p className="helper-text">{limit.description}</p>
      {numeric(
        `${value.kind === "tornado" ? "Track width" : "Footprint radius"} (m)`,
        "extent_m",
        cell,
        Math.floor(Math.hypot(width, height)),
        0.1,
      )}
      {numeric("Duration (ticks)", "duration_ticks", 1, 10000, 1)}
      <p className="helper-text">
        {Number.isFinite(value.duration_ticks)
          ? `${value.duration_ticks * tickSeconds} simulation seconds`
          : "Enter a duration"}{" "}
        · Map meters · Maximum extent is the map diagonal, clipped at city
        edges.
      </p>
      <div className="disaster-coordinate-fields">
        {(["x", "y"] as const).map((axis) => (
          <label key={axis}>
            Origin {axis} (m)
            <input
              aria-label={`Origin ${axis} (m)`}
              type="number"
              min={0}
              max={axis === "x" ? width : height}
              step={0.1}
              value={
                Number.isFinite(value.origin[axis]) ? value.origin[axis] : ""
              }
              onChange={(e) =>
                set({
                  origin: {
                    ...value.origin,
                    [axis]:
                      e.target.value === "" ? NaN : Number(e.target.value),
                  },
                })
              }
              required
            />
          </label>
        ))}
        {value.track_end &&
          (["x", "y"] as const).map((axis) => (
            <label key={`end-${axis}`}>
              Track end {axis} (m)
              <input
                aria-label={`Track end ${axis} (m)`}
                type="number"
                step={0.1}
                value={value.track_end![axis]}
                onChange={(e) =>
                  set({
                    track_end: {
                      ...value.track_end!,
                      [axis]: Number(e.target.value),
                    },
                  })
                }
                required
              />
            </label>
          ))}
      </div>
      <svg
        className="disaster-preview-map"
        viewBox={`0 0 ${width} ${height}`}
        role="button"
        tabIndex={0}
        aria-label="Move disaster origin on the map. Click a location or use arrow keys."
        onKeyDown={(e) => {
          if (disabled) return;
          const delta: Record<string, [number, number]> = {
            ArrowLeft: [-cell, 0],
            ArrowRight: [cell, 0],
            ArrowUp: [0, cell],
            ArrowDown: [0, -cell],
          };
          if (delta[e.key]) {
            e.preventDefault();
            const [x, y] = delta[e.key];
            set({
              origin: {
                x: Math.max(0, Math.min(width, value.origin.x + x)),
                y: Math.max(0, Math.min(height, value.origin.y + y)),
              },
            });
          }
        }}
        onClick={(e) => {
          if (disabled) return;
          const svg = e.currentTarget;
          const p = svg.createSVGPoint();
          p.x = e.clientX;
          p.y = e.clientY;
          const matrix = svg.getScreenCTM();
          if (!matrix) return;
          const local = p.matrixTransform(matrix.inverse());
          set({
            origin: {
              x: Math.max(0, Math.min(width, local.x)),
              y: Math.max(0, Math.min(height, height - local.y)),
            },
          });
        }}
      >
        <rect
          width={width}
          height={height}
          fill="var(--surface, #151b28)"
          stroke="currentColor"
        />
        {footprint ? (
          <polygon
            points={footprint.map((p) => `${p.x},${height - p.y}`).join(" ")}
            fill="#eaa16d44"
            stroke="#eaa16d"
          />
        ) : (
          <circle
            cx={value.origin.x}
            cy={height - value.origin.y}
            r={value.extent_m / (value.kind === "tornado" ? 2 : 1)}
            fill="#eaa16d22"
            stroke="#eaa16d"
            strokeDasharray="2 2"
          />
        )}
        {value.track_end && (
          <line
            x1={value.origin.x}
            y1={height - value.origin.y}
            x2={value.track_end.x}
            y2={height - value.track_end.y}
            stroke="#a9f4de"
            strokeWidth={1}
          />
        )}
        <circle
          cx={value.origin.x}
          cy={height - value.origin.y}
          r={2}
          fill="#a9f4de"
        />
      </svg>
      <small>
        Click to move origin · Arrow keys move by one cell · Solid region is the
        validated maximum envelope. Dashed circle is an unvalidated draft.
      </small>
    </fieldset>
  );
}
