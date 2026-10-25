import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  FlaskConical,
  HeartHandshake,
  Siren,
  Landmark,
  Users,
  Plus,
  ChevronDown,
} from "lucide-react";
import {
  Page,
  Section,
  Field,
  Slider,
  Button,
  ErrorBox,
  Busy,
  CityMark,
} from "../components/ui";
import { useApp, useQuery, messageOf } from "../state/app";
import { defaultConfig, pretty } from "../api/defaults";
import {
  nameKey,
  simulationNames,
  takenMessage,
  uniqueName,
} from "../api/names";
import * as S from "../api/schemas";
import { ApiError } from "../api/client";
import type { Config, Mode } from "../api/types";
const modes: {
  id: Mode;
  title: string;
  description: string;
  icon: typeof FlaskConical;
}[] = [
  {
    id: "sandbox",
    title: "Sandbox",
    description: "Everyday life with no planned event.",
    icon: FlaskConical,
  },
  {
    id: "behavior_lab",
    title: "Behavior Lab",
    description: "How personality shapes relationships and choices.",
    icon: HeartHandshake,
  },
  {
    id: "crisis_lab",
    title: "Crisis Lab",
    description: "How the community handles an emergency.",
    icon: Siren,
  },
  {
    id: "policy_lab",
    title: "Policy Lab",
    description: "Try a rule or program and measure its effects.",
    icon: Landmark,
  },
];
export default function Setup() {
  const { client, capabilities } = useApp();
  const maxAgents = Math.max(10, capabilities?.max_agents ?? 100);
  const location = useLocation(),
    navigate = useNavigate();
  const [config, setConfig] = useState<Config>(() => {
    if (location.state?.config) return { ...location.state.config };
    try {
      return S.config.parse(
        JSON.parse(localStorage.getItem("agentcity-setup-draft") ?? "null"),
      );
    } catch {
      return structuredClone(defaultConfig);
    }
  });
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [errors, setErrors] = useState<Record<string, string>>({});
  const key = useRef(crypto.randomUUID()),
    submitted = useRef(false);
  const profiles = useQuery(() => client.profiles(), [client]);
  const existing = useQuery(() => simulationNames(client), [client]);
  const deduped = useRef(false);
  useEffect(() => {
    if (!existing.data || deduped.current) return;
    deduped.current = true;
    setConfig((c) => ({ ...c, name: uniqueName(c.name, existing.data!) }));
  }, [existing.data]);
  const nameTaken = !!existing.data?.has(nameKey(config.name));
  useEffect(() => {
    localStorage.setItem("agentcity-setup-draft", JSON.stringify(config));
    key.current = crypto.randomUUID();
  }, [config]);
  const update = <K extends keyof Config>(k: K, v: Config[K]) =>
    setConfig((c) => ({ ...c, [k]: v }));
  const submit = async () => {
    if (submitted.current) return;
    if (nameTaken) {
      setErrors({ name: takenMessage });
      return;
    }
    const valid = S.config.safeParse(config);
    if (!valid.success) {
      setErrors(
        Object.fromEntries(
          valid.error.issues.map((i) => [i.path.join("."), i.message]),
        ),
      );
      return;
    }
    submitted.current = true;
    setBusy(true);
    setError("");
    try {
      const s = await client.create(valid.data, key.current);
      localStorage.removeItem("agentcity-setup-draft");
      navigate(`/simulations/${s.id}/loading`);
    } catch (e) {
      setError(messageOf(e));
      if (e instanceof ApiError)
        setErrors(
          Object.fromEntries(
            e.details
              .filter((d) => d.field)
              .map((d) => [d.field!.replace(/^config\./, ""), d.reason]),
          ),
        );
      submitted.current = false;
      setBusy(false);
    }
  };
  return (
    <Page
      title="Build your custom simulation"
      description="Set up the people, the place, and the opening scenario. The city starts paused so you can look around first."
    >
      <div className="setup-layout">
        <form
          className="setup-form"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <Section
            number="01"
            title="Name and type"
            description="Each simulation needs a unique name."
          >
            <Field
              label="Simulation name"
              error={nameTaken ? takenMessage : errors.name}
            >
              <input
                value={config.name}
                maxLength={80}
                onChange={(e) => update("name", e.target.value)}
                placeholder="Name your simulation"
                aria-invalid={nameTaken || !!errors.name}
                required
              />
            </Field>
            <details className="advanced" open={config.mode !== "sandbox"}>
              <summary>
                Simulation type: {modes.find((m) => m.id === config.mode)?.title}
                <ChevronDown size={15} />
              </summary>
              <div className="mode-grid">
                {modes.map(({ id, title, description, icon: Icon }) => (
                  <button
                    key={id}
                    type="button"
                    className={`mode-card ${config.mode === id ? "selected" : ""}`}
                    aria-pressed={config.mode === id}
                    onClick={() => update("mode", id)}
                  >
                    <Icon size={21} />
                    <strong>{title}</strong>
                    <span>{description}</span>
                    <i />
                  </button>
                ))}
              </div>
            </details>
          </Section>
          <Section
            number="02"
            title="Population"
            description="Starting personality and needs for the citizens."
          >
            <Slider
              label="Number of agents"
              min={10}
              max={maxAgents}
              unit=" agents"
              value={config.population}
              onChange={(population) =>
                setConfig((c) => ({
                  ...c,
                  population,
                  custom_agent_ids: c.custom_agent_ids.slice(0, population),
                }))
              }
              hint={`Between 10 and ${maxAgents} citizens. Custom agents count toward this total.`}
            />
            {errors.population && (
              <p className="field-error">{errors.population}</p>
            )}
            <details className="advanced">
              <summary>
                Personality & starting needs
                <ChevronDown size={15} />
              </summary>
              <div className="slider-grid">
                {Object.entries(config.population_traits).map(([k, v]) => (
                  <Slider
                    key={k}
                    label={pretty(k)}
                    value={v}
                    onChange={(value) =>
                      update("population_traits", {
                        ...config.population_traits,
                        [k]: value,
                      })
                    }
                  />
                ))}
              </div>
              <div className="section-divider" />
              <div className="slider-grid">
                <Slider
                  label="Household supplies"
                  value={config.household_supplies}
                  onChange={(v) => update("household_supplies", v)}
                />
                <Slider
                  label="Personality diversity"
                  value={config.personality_diversity}
                  onChange={(v) => update("personality_diversity", v)}
                />
              </div>
            </details>
            <div className="custom-agents-box">
              <div>
                <Users size={18} />
                <strong>Custom agents</strong>
                <span>
                  {config.custom_agent_ids.length} included in{" "}
                  {config.population}
                </span>
              </div>
              {profiles.error ? (
                <ErrorBox error={profiles.error} retry={profiles.reload} />
              ) : !profiles.data ? (
                <Busy />
              ) : profiles.data.length === 0 ? (
                <p>
                  No custom agents created.{" "}
                  <Link to="/settings" state={{ from: "/simulations/new" }}>
                    Create one in Settings <Plus size={13} />
                  </Link>
                </p>
              ) : (
                <div className="profile-picks">
                  {profiles.data.map((p) => (
                    <label key={p.id}>
                      <input
                        type="checkbox"
                        checked={config.custom_agent_ids.includes(p.id)}
                        disabled={
                          config.custom_agent_ids.length >= config.population &&
                          !config.custom_agent_ids.includes(p.id)
                        }
                        onChange={(e) =>
                          update(
                            "custom_agent_ids",
                            e.target.checked
                              ? [...config.custom_agent_ids, p.id]
                              : config.custom_agent_ids.filter(
                                  (id) => id !== p.id,
                                ),
                          )
                        }
                      />
                      {p.profile.name}
                      <small>{p.profile.role}</small>
                    </label>
                  ))}
                </div>
              )}
              {errors.custom_agent_ids && (
                <p className="field-error">{errors.custom_agent_ids}</p>
              )}
            </div>
          </Section>
          <Section
            number="03"
            title="Environment"
            description="Resources, density, infrastructure, and setting."
          >
            <details className="advanced">
              <summary>
                Environment settings
                <ChevronDown size={15} />
              </summary>
              <span className="field-caption">SETTLEMENT</span>
              <div className="segmented">
                <button
                  type="button"
                  className={
                    config.environment.settlement === "suburb" ? "active" : ""
                  }
                  onClick={() =>
                    update("environment", {
                      ...config.environment,
                      settlement: "suburb",
                    })
                  }
                >
                  Suburb
                </button>
                <button
                  type="button"
                  className={
                    config.environment.settlement === "urban" ? "active" : ""
                  }
                  onClick={() =>
                    update("environment", {
                      ...config.environment,
                      settlement: "urban",
                    })
                  }
                >
                  Urban
                </button>
              </div>
              <div className="slider-grid">
                {(
                  [
                    "resource_availability",
                    "population_density",
                    "infrastructure_capacity",
                    "initial_community_trust",
                  ] as const
                ).map((k) => (
                  <Slider
                    key={k}
                    label={pretty(k)}
                    value={config.environment[k]}
                    onChange={(v) =>
                      update("environment", { ...config.environment, [k]: v })
                    }
                  />
                ))}
              </div>
            </details>
          </Section>
          <Section
            number="04"
            title="Scenario"
            description="Optional. Leave blank to watch everyday life."
          >
            <Field
              label="Scenario description"
              hint="Describe people, creatures, weather or an event. Review its generated 3D scene and effects before it begins."
              error={errors.scenario_description}
            >
              <textarea
                maxLength={4000}
                rows={5}
                placeholder="Describe the city and what you would like to happen…"
                value={config.scenario_description}
                onChange={(e) => update("scenario_description", e.target.value)}
              />
            </Field>
            <div className="suggestion-chips">
              {[
                "Dinosaurs in the town square",
                "An alien arrival during a festival",
                "A farmers market and garden",
                "Robots deliver aid after a storm",
              ].map((s) => (
                <button
                  type="button"
                  key={s}
                  onClick={() => update("scenario_description", s)}
                >
                  {s} <Plus size={12} />
                </button>
              ))}
            </div>
            <details className="advanced">
              <summary>
                Advanced world settings <ChevronDown size={15} />
              </summary>
              <div className="two-col">
                <Field label="Seed" error={errors.seed}>
                  <input
                    type="number"
                    min={0}
                    max={2147483647}
                    value={config.seed}
                    onChange={(e) => update("seed", Number(e.target.value))}
                  />
                </Field>
                <Field label="Maximum ticks" error={errors.max_ticks}>
                  <input
                    type="number"
                    min={1}
                    max={10000}
                    value={config.max_ticks}
                    onChange={(e) =>
                      update("max_ticks", Number(e.target.value))
                    }
                  />
                </Field>
              </div>
            </details>
          </Section>
          {error && <ErrorBox error={error} />}
          <div className="form-footer">
            <p>
              <span>The simulation starts paused.</span>
            </p>
            <Button type="submit" disabled={busy || nameTaken}>
              {busy ? "Creating simulation…" : "Create simulation"}
              <ArrowRight size={18} />
            </Button>
          </div>
        </form>
        <aside className="setup-aside">
          <div className="mini-city-icon">
            <CityMark />
          </div>
          <h2>{config.name || "Untitled simulation"}</h2>
          <p>{modes.find((m) => m.id === config.mode)?.description}</p>
          <dl>
            <div>
              <dt>Citizens</dt>
              <dd>{config.population}</dd>
            </div>
            <div>
              <dt>Setting</dt>
              <dd>{pretty(config.environment.settlement)}</dd>
            </div>
            <div>
              <dt>Type</dt>
              <dd>{modes.find((m) => m.id === config.mode)?.title}</dd>
            </div>
            <div>
              <dt>Custom agents</dt>
              <dd>{config.custom_agent_ids.length}</dd>
            </div>
          </dl>
        </aside>
      </div>
    </Page>
  );
}
