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
} from "../components/ui";
import { useApp, useQuery, messageOf } from "../state/app";
import { defaultConfig, pretty } from "../api/defaults";
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
    title: "Everyday life",
    description: "Follow ten neighbors through their everyday lives.",
    icon: FlaskConical,
  },
  {
    id: "behavior_lab",
    title: "Behavior Lab",
    description: "Explore human connections.",
    icon: HeartHandshake,
  },
  {
    id: "crisis_lab",
    title: "Crisis Lab",
    description: "Put resilience to the test.",
    icon: Siren,
  },
  {
    id: "policy_lab",
    title: "Policy Lab",
    description: "See ideas become impact.",
    icon: Landmark,
  },
];
export default function Setup() {
  const { client } = useApp();
  const location = useLocation(),
    navigate = useNavigate();
  const [config, setConfig] = useState<Config>(() => {
    if (location.state?.config)
      return {
        ...location.state.config,
        population: 10,
        custom_agent_ids: location.state.config.custom_agent_ids.slice(0, 10),
      };
    try {
      const draft = S.config.parse(
        JSON.parse(localStorage.getItem("agentcity-setup-draft") ?? "null"),
      );
      return {
        ...draft,
        population: 10,
        custom_agent_ids: draft.custom_agent_ids.slice(0, 10),
      };
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
  useEffect(() => {
    localStorage.setItem("agentcity-setup-draft", JSON.stringify(config));
    key.current = crypto.randomUUID();
  }, [config]);
  const update = <K extends keyof Config>(k: K, v: Config[K]) =>
    setConfig((c) => ({ ...c, [k]: v }));
  const submit = async () => {
    if (submitted.current) return;
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
      eyebrow="THE NEXT CHAPTER IS YOURS"
      title="Ten people. A world of little moments."
      description="Make a small neighborhood, get to know each person, and drop into their everyday lives."
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
            title="Give your world a beginning"
            description="A name, a question, a little curiosity."
          >
            <Field label="Simulation name" error={errors.name}>
              <input
                value={config.name}
                maxLength={80}
                onChange={(e) => update("name", e.target.value)}
                placeholder="Name your world"
                required
              />
            </Field>
            <div className="everyday-intro">
              <HeartHandshake size={22} />
              <p>
                <strong>Everyday life, up close.</strong>
                <span>
                  Visit your neighbors. Follow a conversation. See friendships
                  grow.
                </span>
              </p>
            </div>
            <details className="advanced">
              <summary>
                Other ways to explore
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
            title="Meet the neighborhood"
            description="Different people. Shared streets. Endless possibilities."
          >
            <div className="population-control">
              <div>
                <h3>A cast you can know by name</h3>
                <p>Ten neighbors. Room for every little story.</p>
              </div>
              <div className="fixed-cast-size">
                <input
                  aria-label="Population"
                  type="number"
                  value={10}
                  readOnly
                />
                <span>NEIGHBORS</span>
              </div>
            </div>
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
                <strong>Bring familiar faces</strong>
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
                          config.custom_agent_ids.length >= 10 &&
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
            title="A place to call home"
            description="A few homes, shared spaces, and neighbors just a short walk away."
          >
            <details className="advanced">
              <summary>
                Adjust their surroundings
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
                  Suburb <span>Room to grow</span>
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
                  Urban <span>Closer together</span>
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
            title="Introduce a what if"
            description="Optional. Set something in motion, or simply watch everyday life."
          >
            <Field
              label="Your opening scenario"
              hint="You’ll review the interpreted effects before anything changes."
              error={errors.scenario_description}
            >
              <textarea
                maxLength={4000}
                rows={5}
                placeholder="What if a sudden flood tested how well this neighborhood looks out for each other?"
                value={config.scenario_description}
                onChange={(e) => update("scenario_description", e.target.value)}
              />
            </Field>
            <div className="suggestion-chips">
              {[
                "A neighborhood festival",
                "A sudden flood",
                "A supply shortage",
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
              Your city starts paused.
              <br />
              <span>Take a look around before you press Play.</span>
            </p>
            <Button type="submit" disabled={busy}>
              {busy ? "Creating your world…" : "Create simulation"}
              <ArrowRight size={18} />
            </Button>
          </div>
        </form>
        <aside className="setup-aside">
          <div className="mini-city-icon">
            <Users size={32} />
          </div>
          <div className="eyebrow">A WORLD IN THE MAKING</div>
          <h2>{config.name || "Your next world"}</h2>
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
              <dt>Perspective</dt>
              <dd>{pretty(config.mode)}</dd>
            </div>
          </dl>
          <div className="aside-note">
            <span>✳</span>
            <p>
              Small changes can lead to surprising stories. There’s no perfect
              starting point.
            </p>
          </div>
          <small>
            Exploratory simulations, not predictions of human behavior.
          </small>
        </aside>
      </div>
    </Page>
  );
}
