import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Check,
  Plus,
  Sun,
  Moon,
  Box,
  Map,
  Trash2,
  Pencil,
  Users,
  Keyboard,
  Activity,
} from "lucide-react";
import {
  Page,
  Section,
  Field,
  Slider,
  Button,
  ErrorBox,
  Busy,
  Modal,
  Empty,
} from "../components/ui";
import { useApp, useQuery, messageOf } from "../state/app";
import { ApiError } from "../api/client";
import type {
  CustomAgent,
  Profile,
  Settings as Preferences,
} from "../api/types";
import { defaultProfile, pretty } from "../api/defaults";
import { formatChord, isMac, shortcutChoices } from "../platform";
import * as S from "../api/schemas";
type Shortcuts = Preferences["shortcuts"];
type ShortcutAction = keyof Shortcuts;
type SettingsOperation = {
  patch: Partial<Preferences>;
  request?: { key: string; body: Preferences };
};
export default function Settings() {
  const {
    client,
    settings,
    setSettings,
    notice,
    audioPreferences,
    setAudioPreferences,
  } = useApp();
  const [shortcuts, setShortcuts] = useState<Shortcuts>(settings.shortcuts),
    [shortcutsDirty, setShortcutsDirty] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [editing, setEditing] = useState<CustomAgent | "new" | null>(null),
    [deleting, setDeleting] = useState<CustomAgent | null>(null);
  useEffect(() => {
    if (!shortcutsDirty) setShortcuts(settings.shortcuts);
  }, [settings.shortcuts, shortcutsDirty]);
  const confirmed = useRef(settings);
  const operations = useRef<SettingsOperation[]>([]);
  const draining = useRef<Promise<void> | null>(null);
  const shortcutsOperation = useRef<SettingsOperation | null>(null);
  if (!operations.current.length && !draining.current)
    confirmed.current = settings;
  const publish = () =>
    setSettings(
      operations.current.reduce(
        (value, operation) => ({ ...value, ...operation.patch }),
        confirmed.current,
      ),
    );
  const drain = () => {
    if (draining.current) return draining.current;
    draining.current = (async () => {
      while (operations.current.length) {
        const operation = operations.current[0];
        // Freeze the normalized body and expected version with the key. A lost
        // response leaves this exact request at the head of the queue for retry.
        operation.request ??= {
          key: crypto.randomUUID(),
          body: S.settings.parse({ ...confirmed.current, ...operation.patch }),
        };
        try {
          confirmed.current = await client.saveSettings(
            operation.request.body,
            operation.request.key,
          );
        } catch (e) {
          if (
            e instanceof ApiError &&
            !e.retryable &&
            e.code !== "CONTRACT_ERROR"
          ) {
            operation.request = undefined;
            if (e.code === "CONTROL_CONFLICT")
              confirmed.current = await client.settings();
          }
          publish();
          throw e;
        }
        // A confirmed save has ended; later operations get their own key and
        // use the returned version. Keep queued appearance edits visible.
        operations.current.shift();
        publish();
      }
    })().finally(() => {
      draining.current = null;
    });
    return draining.current;
  };
  const persist = (patch: Partial<Preferences>) => {
    operations.current.push({ patch });
    publish();
    setError("");
    void drain().catch((e) => setError(messageOf(e)));
  };
  const profiles = useQuery(() => client.profiles(), [client]);
  const usage = useQuery(() => client.usage(), [client]);
  const totalTokens = usage.data
    ? usage.data.input_tokens + usage.data.output_tokens
    : 0;
  const inputShare =
    totalTokens && usage.data
      ? (usage.data.input_tokens / totalTokens) * 100
      : 0;
  const location = useLocation(),
    navigate = useNavigate();
  const shortcutOwner = (chord: string, except: ShortcutAction) =>
    (Object.keys(shortcuts) as ShortcutAction[]).find(
      (k) => k !== except && shortcuts[k] === chord,
    );
  const save = async (next = false) => {
    setBusy(true);
    setError("");
    try {
      if (
        !shortcutsOperation.current ||
        !operations.current.includes(shortcutsOperation.current)
      ) {
        shortcutsOperation.current = { patch: { shortcuts } };
        operations.current.push(shortcutsOperation.current);
      }
      await drain();
      shortcutsOperation.current = null;
      setShortcutsDirty(false);
      notice("Settings saved.");
      if (next) navigate("/simulations/new");
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Page
      title="Settings"
      description="Changes to appearance, view, and motion apply right away."
      ambient="settings"
    >
      <div className="settings-layout">
        <div>
          <Section number="01" title="Appearance">
            <span className="field-caption">Color theme</span>
            <div className="appearance-options">
              <button
                className={settings.theme === "dark" ? "selected" : ""}
                aria-pressed={settings.theme === "dark"}
                onClick={() => persist({ theme: "dark" })}
              >
                <div className="theme-preview dark-preview">
                  <i />
                  <i />
                  <i />
                </div>
                <span>
                  <Moon size={16} />
                  Dark{settings.theme === "dark" && <Check size={16} />}
                </span>
              </button>
              <button
                className={settings.theme === "light" ? "selected" : ""}
                aria-pressed={settings.theme === "light"}
                onClick={() => persist({ theme: "light" })}
              >
                <div className="theme-preview light-preview">
                  <i />
                  <i />
                  <i />
                </div>
                <span>
                  <Sun size={16} />
                  Light pastel
                  {settings.theme === "light" && <Check size={16} />}
                </span>
              </button>
            </div>
            <span className="field-caption">City view</span>
            <div className="segmented">
              <button
                className={settings.view_mode === "3d" ? "active" : ""}
                aria-pressed={settings.view_mode === "3d"}
                onClick={() => persist({ view_mode: "3d" })}
              >
                <Box size={17} />
                3D city
              </button>
              <button
                className={settings.view_mode === "2d" ? "active" : ""}
                aria-pressed={settings.view_mode === "2d"}
                onClick={() => persist({ view_mode: "2d" })}
              >
                <Map size={17} />
                2D map
              </button>
            </div>
            <label className="setting-toggle">
              <span>
                <strong>Reduce motion</strong>
                <small>
                  Moves the camera without easing, removes button glow, turns
                  off the mouse trail, and stops background animation.
                </small>
              </span>
              <input
                type="checkbox"
                checked={settings.reduce_motion}
                onChange={(e) => persist({ reduce_motion: e.target.checked })}
              />
            </label>
            <label className="setting-toggle">
              <span>
                <strong>Autosave</strong>
                <small>
                  Save simulations automatically at regular checkpoints.
                  Snapshots before events and when leaving a simulation are
                  always saved.
                </small>
              </span>
              <input
                type="checkbox"
                checked={settings.autosave}
                onChange={(e) => persist({ autosave: e.target.checked })}
              />
            </label>
          </Section>
          <Section number="02" title="Conversation audio">
            {(
              [
                [
                  "auto_play_conversations",
                  "Play conversations automatically",
                  "Opening two citizens talking plays their conversation.",
                ],
                [
                  "slow_simulation_for_audio",
                  "Slow simulation in conversation view",
                  "Use 0.25× speed when entering conversation view and restore your previous speed when leaving.",
                ],
              ] as const
            ).map(([key, title, description]) => (
              <label className="setting-toggle" key={key}>
                <span>
                  <strong>{title}</strong>
                  <small>{description}</small>
                </span>
                <input
                  type="checkbox"
                  checked={audioPreferences[key]}
                  onChange={(e) =>
                    setAudioPreferences({
                      ...audioPreferences,
                      [key]: e.target.checked,
                    })
                  }
                />
              </label>
            ))}
          </Section>
          <Section
            id="custom-agents"
            number="03"
            title="Custom agents"
            description="Create citizens you can add to any simulation."
          >
            <div className="section-toolbar">
              <p>Edits apply to simulations created afterward.</p>
              <Button kind="secondary" onClick={() => setEditing("new")}>
                <Plus size={16} />
                Create custom agent
              </Button>
            </div>
            {profiles.error ? (
              <ErrorBox error={profiles.error} retry={profiles.reload} />
            ) : !profiles.data ? (
              <Busy />
            ) : profiles.data.length ? (
              <div className="saved-profiles">
                {profiles.data.map((p) => (
                  <article key={p.id}>
                    <div className="avatar">
                      {p.profile.name
                        .split(" ")
                        .map((s) => s[0])
                        .join("")}
                    </div>
                    <div>
                      <h3>{p.profile.name}</h3>
                      <p>
                        {p.profile.role} · Age {p.profile.age}
                      </p>
                    </div>
                    <button
                      className="icon-button"
                      aria-label={`Edit ${p.profile.name}`}
                      onClick={() => setEditing(p)}
                    >
                      <Pencil size={16} />
                    </button>
                    <button
                      className="icon-button"
                      aria-label={`Delete ${p.profile.name}`}
                      onClick={() => setDeleting(p)}
                    >
                      <Trash2 size={16} />
                    </button>
                  </article>
                ))}
              </div>
            ) : (
              <Empty title="No custom agents created">
                <Users size={14} /> Create one to add it to a simulation.
              </Empty>
            )}
          </Section>
          <Section
            number="04"
            title="Keyboard shortcuts"
            description="Shortcuts work when the city map has focus."
          >
            <div className="shortcut-editor">
              {(Object.keys(shortcuts) as ShortcutAction[]).map((k) => {
                const choices = shortcutChoices[k].includes(shortcuts[k])
                  ? shortcutChoices[k]
                  : [shortcuts[k], ...shortcutChoices[k]];
                return (
                  <Field key={k} label={pretty(k)}>
                    <select
                      aria-label={`${pretty(k)} shortcut`}
                      disabled={busy}
                      value={shortcuts[k]}
                      onChange={(e) => {
                        shortcutsOperation.current = null;
                        setShortcutsDirty(true);
                        setShortcuts((s) => ({ ...s, [k]: e.target.value }));
                      }}
                    >
                      {choices.map((chord) => {
                        const owner = shortcutOwner(chord, k);
                        return (
                          <option key={chord} value={chord} disabled={!!owner}>
                            {formatChord(chord)}
                            {owner ? ` (used by ${pretty(owner)})` : ""}
                          </option>
                        );
                      })}
                    </select>
                  </Field>
                );
              })}
            </div>
            <p className="helper-text">
              <Keyboard size={14} />
              Showing {isMac ? "Mac (⌘ Command)" : "Windows (Ctrl)"} keys for
              this device. Each key can only be used for one action.
            </p>
          </Section>
          {error && <ErrorBox error={error} />}
          <div className="form-footer">
            <Button
              kind="secondary"
              disabled={busy || !shortcutsDirty}
              onClick={() => void save()}
            >
              Save shortcuts
              <Check size={16} />
            </Button>
            <Button disabled={busy} onClick={() => void save(true)}>
              Save and create a new simulation
              <ArrowRight size={16} />
            </Button>
          </div>
          {location.state?.from?.startsWith("/simulations/") && (
            <Link className="back-link" to={location.state.from}>
              <ArrowRight size={14} />
              Return to your paused simulation
            </Link>
          )}
        </div>
        <aside className="settings-aside">
          <h2>
            <Activity size={18} /> Token usage
          </h2>
          <p>
            Model usage across all your simulations. Replaying history makes no
            model calls.
          </p>
          {usage.error ? (
            <ErrorBox error={usage.error} retry={usage.reload} />
          ) : !usage.data ? (
            <Busy />
          ) : (
            <>
              <div className="token-meter">
                <span className="field-caption">Total tokens</span>
                <strong className="token-meter-total">
                  {totalTokens.toLocaleString()}
                </strong>
                <div
                  className="token-meter-track"
                  role="img"
                  aria-label={`Token usage: ${usage.data.input_tokens.toLocaleString()} input tokens and ${usage.data.output_tokens.toLocaleString()} output tokens. ${usage.data.cached_tokens.toLocaleString()} cached tokens are included in input.`}
                >
                  <span
                    className="token-meter-input"
                    style={{ width: `${inputShare}%` }}
                  />
                  <span
                    className="token-meter-output"
                    style={{ width: `${totalTokens ? 100 - inputShare : 0}%` }}
                  />
                </div>
                <div className="token-meter-legend" aria-hidden="true">
                  <span>
                    <i className="token-meter-input" /> Input
                  </span>
                  <span>
                    <i className="token-meter-output" /> Output
                  </span>
                </div>
                <p className="helper-text">
                  {totalTokens === 0
                    ? "No token usage recorded yet."
                    : "Cached tokens are included in input totals."}
                </p>
                <Button kind="ghost" onClick={usage.reload}>
                  Refresh usage
                </Button>
              </div>
              <dl className="usage-stats">
                <div>
                  <dt>Input tokens</dt>
                  <dd>{usage.data.input_tokens.toLocaleString()}</dd>
                </div>
                <div>
                  <dt>Output tokens</dt>
                  <dd>{usage.data.output_tokens.toLocaleString()}</dd>
                </div>
                <div>
                  <dt>Cached tokens</dt>
                  <dd>{usage.data.cached_tokens.toLocaleString()}</dd>
                </div>
                <div>
                  <dt>Model calls</dt>
                  <dd>{usage.data.calls}</dd>
                </div>
                <div>
                  <dt>Failed calls</dt>
                  <dd>{usage.data.failed_calls}</dd>
                </div>
              </dl>
              <div className="cost-card">
                <span>Estimated cost</span>
                <strong>
                  {usage.data.estimated_cost_usd === null
                    ? "Unavailable"
                    : `$${usage.data.estimated_cost_usd.toFixed(4)}`}
                </strong>
                <small>
                  {usage.data.pricing_as_of
                    ? `Pricing as of ${new Date(usage.data.pricing_as_of).toLocaleDateString()}`
                    : "No configured current pricing."}
                </small>
              </div>
              {client.mode === "mock" && (
                <p className="helper-text">
                  Fixture review makes no model calls. Token totals are zero.
                </p>
              )}
            </>
          )}
        </aside>
      </div>
      {editing && (
        <ProfileEditor
          existing={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            profiles.reload();
            notice("Custom profile saved for future citizens.");
          }}
        />
      )}
      {deleting && (
        <Modal
          title={`Delete ${deleting.profile.name}?`}
          onClose={() => setDeleting(null)}
          busy={busy}
        >
          <p>
            This removes the saved custom agent. Citizens already in a
            simulation keep their copy.
          </p>
          {error && <ErrorBox error={error} />}
          <div className="modal-actions">
            <Button
              kind="ghost"
              disabled={busy}
              onClick={() => setDeleting(null)}
            >
              Cancel
            </Button>
            <Button
              kind="danger"
              disabled={busy}
              onClick={() => {
                setBusy(true);
                void client
                  .deleteProfile(deleting)
                  .then(() => {
                    setDeleting(null);
                    profiles.reload();
                  })
                  .catch((e) => setError(messageOf(e)))
                  .finally(() => setBusy(false));
              }}
            >
              Delete profile
            </Button>
          </div>
        </Modal>
      )}
    </Page>
  );
}
export function ProfileEditor({
  existing,
  onClose,
  onSaved,
}: {
  existing?: CustomAgent;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { client } = useApp();
  const [p, setP] = useState<Profile>(
      structuredClone(existing?.profile ?? defaultProfile),
    ),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [errors, setErrors] = useState<Record<string, string>>({});
  const profileKey = useRef(crypto.randomUUID());
  const update = <K extends keyof Profile>(k: K, v: Profile[K]) => {
    profileKey.current = crypto.randomUUID();
    setP((p) => ({ ...p, [k]: v }));
  };
  const save = async () => {
    const parsed = S.profile.safeParse(p);
    if (!parsed.success) {
      setErrors(
        Object.fromEntries(
          parsed.error.issues.map((i) => [i.path.join("."), i.message]),
        ),
      );
      return;
    }
    setBusy(true);
    try {
      await client.saveProfile(parsed.data, existing, profileKey.current);
      onSaved();
    } catch (e) {
      setError(messageOf(e));
      setBusy(false);
    }
  };
  return (
    <Modal
      title={existing ? `Edit ${existing.profile.name}` : "New custom agent"}
      onClose={onClose}
      busy={busy}
      wide
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <div className="two-col">
          <Field label="Name" error={errors.name}>
            <input
              autoFocus
              required
              maxLength={80}
              value={p.name}
              onChange={(e) => update("name", e.target.value)}
            />
          </Field>
          <Field label="Age" error={errors.age}>
            <input
              required
              type="number"
              min={0}
              max={120}
              value={p.age}
              onChange={(e) => update("age", Number(e.target.value))}
            />
          </Field>
        </div>
        <Field label="Role" error={errors.role}>
          <input
            required
            maxLength={80}
            value={p.role}
            onChange={(e) => update("role", e.target.value)}
            placeholder="Teacher, gardener, community organizer…"
          />
        </Field>
        <div className="slider-grid">
          {Object.entries(p.traits).map(([k, v]) => (
            <Slider
              label={pretty(k)}
              key={k}
              value={v}
              onChange={(v) => update("traits", { ...p.traits, [k]: v })}
            />
          ))}
        </div>
        <Field label="Personality">
          <textarea
            value={p.personality}
            maxLength={2000}
            onChange={(e) => update("personality", e.target.value)}
            placeholder="What are they like?"
          />
        </Field>
        <Field label="Background">
          <textarea
            value={p.background}
            maxLength={2000}
            onChange={(e) => update("background", e.target.value)}
            placeholder="Where does their story begin?"
          />
        </Field>
        <Field label="Values (one per line)" error={errors.values}>
          <textarea
            value={p.values.join("\n")}
            onChange={(e) => update("values", e.target.value.split("\n"))}
          />
        </Field>
        <Field label="Primary goal">
          <input
            value={p.primary_goal}
            maxLength={2000}
            onChange={(e) => update("primary_goal", e.target.value)}
          />
        </Field>
        <details className="advanced">
          <summary>
            More traits <ChevronDownIcon />
          </summary>
          {(["secondary_goals", "skills", "desires", "fears"] as const).map(
            (k) => (
              <Field
                key={k}
                label={`${pretty(k)} (one per line)`}
                error={errors[k]}
              >
                <textarea
                  value={p[k].join("\n")}
                  onChange={(e) => update(k, e.target.value.split("\n"))}
                />
              </Field>
            ),
          )}
          <Field label="Personal history">
            <textarea
              value={p.personal_history}
              maxLength={2000}
              onChange={(e) => update("personal_history", e.target.value)}
            />
          </Field>
          <Field label="Physical attributes">
            <textarea
              value={p.physical_attributes}
              maxLength={2000}
              onChange={(e) => update("physical_attributes", e.target.value)}
            />
          </Field>
          {(["intelligence", "mobility", "social_needs"] as const).map((k) => (
            <Slider
              key={k}
              label={pretty(k)}
              value={p[k]}
              onChange={(v) => update(k, v)}
            />
          ))}
        </details>
        {error && <ErrorBox error={error} />}
        <div className="modal-actions">
          <Button kind="ghost" disabled={busy} onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy}>
            {busy ? "Saving…" : "Save custom agent"}
            <Check size={16} />
          </Button>
        </div>
      </form>
    </Modal>
  );
}
function ChevronDownIcon() {
  return <span aria-hidden="true">⌄</span>;
}
