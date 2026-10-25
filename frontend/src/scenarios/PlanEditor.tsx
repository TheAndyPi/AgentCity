import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { pretty } from "../api/defaults";
import { Field } from "../components/ui";
import type { EngineCapabilities, Plan } from "./schema";

type Schema = {
  type?: string;
  enum?: unknown[];
  const?: unknown;
  anyOf?: Schema[];
  $ref?: string;
  default?: unknown;
  minimum?: number;
  maximum?: number;
  properties?: Record<string, Schema>;
  required?: string[];
  $defs?: Record<string, Schema>;
};
type Op = Record<string, unknown>;
const SKIP = new Set(["type", "id", "timing", "audience", "rationale"]);

function resolve(schema: Schema, root: Schema): Schema {
  if (schema.$ref)
    return resolve(root.$defs?.[schema.$ref.split("/").pop()!] ?? {}, root);
  if (schema.anyOf) {
    const options = schema.anyOf.filter((s) => s.type !== "null");
    const nullable = options.length < schema.anyOf.length;
    return {
      ...resolve(options[0] ?? {}, root),
      default: schema.default,
      ...(nullable ? { nullable: true } : {}),
    } as Schema;
  }
  return schema;
}

function initial(schema: Schema): unknown {
  if (schema.default !== undefined) return schema.default;
  if (schema.enum) return schema.enum[0];
  if (schema.type === "boolean") return true;
  if (schema.type === "number" || schema.type === "integer")
    return schema.minimum ?? 0;
  if (schema.type === "string") return "";
  return null;
}

export function blankOperation(
  type: string,
  caps: EngineCapabilities,
  index: number,
): Op {
  const root = caps.operations.find((o) => o.type === type)!
    .parameters as Schema;
  const op: Op = { type, id: `op${index + 1}`, rationale: "" };
  for (const name of root.required ?? []) {
    if (SKIP.has(name)) continue;
    op[name] = initial(resolve(root.properties![name], root));
  }
  return op;
}

function Input({
  name,
  schema,
  value,
  onChange,
}: {
  name: string;
  schema: Schema & { nullable?: boolean };
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const label = pretty(name);
  if (schema.enum)
    return (
      <Field label={label}>
        <select
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value || null)}
        >
          {schema.nullable && <option value="">None</option>}
          {schema.enum.map((v) => (
            <option key={String(v)} value={String(v)}>
              {pretty(String(v))}
            </option>
          ))}
        </select>
      </Field>
    );
  if (schema.type === "boolean")
    return (
      <label className="checkbox">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
        />{" "}
        {label}
      </label>
    );
  if (schema.type === "number" || schema.type === "integer")
    return (
      <Field
        label={`${label}${schema.minimum !== undefined && schema.maximum !== undefined ? ` (${schema.minimum}–${schema.maximum})` : ""}`}
      >
        <input
          type="number"
          step={schema.type === "integer" ? 1 : "any"}
          min={schema.minimum}
          max={schema.maximum}
          value={value === null || value === undefined ? "" : String(value)}
          onChange={(e) =>
            onChange(
              e.target.value === ""
                ? null
                : schema.type === "integer"
                  ? Math.round(Number(e.target.value))
                  : Number(e.target.value),
            )
          }
        />
      </Field>
    );
  return (
    <Field label={label}>
      <input
        value={String(value ?? "")}
        onChange={(e) =>
          onChange(e.target.value || (schema.nullable ? null : ""))
        }
      />
    </Field>
  );
}

function OperationEditor({
  op,
  caps,
  onChange,
  onRemove,
}: {
  op: Op;
  caps: EngineCapabilities;
  onChange: (op: Op) => void;
  onRemove: () => void;
}) {
  const meta = caps.operations.find((o) => o.type === op.type);
  if (!meta) return null;
  const root = meta.parameters as Schema;
  const timing = (op.timing as Record<string, number | null> | undefined) ?? {};
  const audience = (op.audience as Record<string, unknown> | undefined) ?? {};
  const audienceSchema = root.$defs?.Audience;
  const setTiming = (key: string, value: unknown) =>
    onChange({ ...op, timing: { ...timing, [key]: value } });
  const target = caps.policy_targets.find((t) => t.target === op.target);
  return (
    <fieldset className="plan-operation">
      <legend>
        {pretty(String(op.type))}
        <button
          type="button"
          className="text-button"
          onClick={onRemove}
          aria-label="Remove change"
        >
          <Trash2 size={13} />
        </button>
      </legend>
      <p className="muted">{meta.description}</p>
      {Object.entries(root.properties ?? {})
        .filter(([name]) => !SKIP.has(name))
        .map(([name, raw]) => (
          <Input
            key={name}
            name={name}
            schema={resolve(raw, root)}
            value={op[name]}
            onChange={(v) => onChange({ ...op, [name]: v })}
          />
        ))}
      {target && (
        <p className="helper-text">
          {target.description} Allowed {target.minimum}–{target.maximum}{" "}
          {target.unit}.
        </p>
      )}
      {audienceSchema && "audience" in (root.properties ?? {}) && (
        <div className="plan-row">
          <Input
            name="audience"
            schema={resolve(audienceSchema.properties!.kind, root)}
            value={audience.kind ?? "all_citizens"}
            onChange={(v) =>
              onChange({ ...op, audience: { ...audience, kind: v } })
            }
          />
          <Input
            name="share of audience"
            schema={resolve(audienceSchema.properties!.share, root)}
            value={audience.share ?? 1}
            onChange={(v) =>
              onChange({ ...op, audience: { ...audience, share: v } })
            }
          />
          {audience.kind === "region" && (
            <Input
              name="audience region"
              schema={resolve(audienceSchema.properties!.region, root)}
              value={audience.region ?? null}
              onChange={(v) =>
                onChange({ ...op, audience: { ...audience, region: v } })
              }
            />
          )}
        </div>
      )}
      <div className="plan-row">
        <Input
          name="start tick"
          schema={{ type: "integer", minimum: 0, maximum: 500 }}
          value={timing.start_tick ?? 0}
          onChange={(v) => setTiming("start_tick", v ?? 0)}
        />
        <Input
          name="duration ticks (blank = scenario default)"
          schema={{ type: "integer", minimum: 1, maximum: 1000 }}
          value={timing.duration_ticks ?? null}
          onChange={(v) => setTiming("duration_ticks", v)}
        />
      </div>
    </fieldset>
  );
}

export function PlanEditor({
  plan,
  caps,
  onChange,
}: {
  plan: Plan;
  caps: EngineCapabilities;
  onChange: (plan: Plan) => void;
}) {
  const [adding, setAdding] = useState(caps.operations[0]?.type ?? "");
  const operations = (plan.operations as Op[] | undefined) ?? [];
  const set = (key: string, value: unknown) =>
    onChange({ ...plan, [key]: value });
  const metrics = new Set((plan.metrics as string[] | undefined) ?? []);
  return (
    <div className="plan-editor">
      <Field label="Title">
        <input
          maxLength={80}
          value={String(plan.title ?? "")}
          onChange={(e) => set("title", e.target.value)}
        />
      </Field>
      <Field label="What residents can observe">
        <textarea
          rows={2}
          maxLength={500}
          value={String(plan.public_description ?? "")}
          onChange={(e) => set("public_description", e.target.value)}
        />
      </Field>
      <div className="plan-row">
        <Field label="Duration">
          <select
            value={String(plan.duration)}
            onChange={(e) => set("duration", e.target.value)}
          >
            <option value="temporary">
              Temporary (reverts after the window)
            </option>
            <option value="permanent">Permanent</option>
          </select>
        </Field>
        <Field label="Measurement window (ticks)">
          <input
            type="number"
            min={4}
            max={500}
            value={Number(plan.measurement_ticks ?? 36)}
            onChange={(e) =>
              set("measurement_ticks", Math.round(Number(e.target.value)))
            }
          />
        </Field>
      </div>
      <h4 className="panel-label">CHANGES</h4>
      {operations.map((op, i) => (
        <OperationEditor
          key={`${String(op.id)}-${i}`}
          op={op}
          caps={caps}
          onChange={(next) =>
            set(
              "operations",
              operations.map((o, j) => (j === i ? next : o)),
            )
          }
          onRemove={() =>
            set(
              "operations",
              operations.filter((_, j) => j !== i),
            )
          }
        />
      ))}
      <div className="plan-row">
        <select
          value={adding}
          onChange={(e) => setAdding(e.target.value)}
          aria-label="Change to add"
        >
          {caps.operations.map((o) => (
            <option key={o.type} value={o.type}>
              {pretty(o.type)}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="button secondary"
          onClick={() =>
            set("operations", [
              ...operations,
              blankOperation(adding, caps, operations.length),
            ])
          }
        >
          <Plus size={14} /> Add change
        </button>
      </div>
      <h4 className="panel-label">MEASUREMENTS</h4>
      <div className="plan-metric-picker">
        {Object.entries(caps.metrics).map(([id, description]) => (
          <label className="checkbox" key={id} title={description}>
            <input
              type="checkbox"
              checked={metrics.has(id)}
              onChange={(e) => {
                const next = new Set(metrics);
                if (e.target.checked) next.add(id);
                else next.delete(id);
                set("metrics", [...next]);
              }}
            />{" "}
            {pretty(id)}
          </label>
        ))}
      </div>
    </div>
  );
}

export function manualPlan(prompt: string): Plan {
  const text = prompt.trim() || "A custom scenario";
  return {
    title: text.slice(0, 80),
    category: "mixed",
    description: text.slice(0, 1000),
    public_description: text.slice(0, 500),
    duration: "temporary",
    measurement_ticks: 36,
    affected_systems: [],
    operations: [],
    agent_knowledge: "",
    metrics: ["happiness", "stress"],
    assumptions: [],
    unsupported: [],
    source: "manual",
    prompt: text.slice(0, 2000),
  };
}
