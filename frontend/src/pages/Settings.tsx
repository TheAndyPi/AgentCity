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
import type {
  CustomAgent,
  Profile,
  Settings as Preferences,
} from "../api/types";
import { defaultProfile, pretty } from "../api/defaults";
import * as S from "../api/schemas";
export default function Settings() {
  const { client, settings, setSettings, notice } = useApp();
  const [draft, setDraft] = useState<Preferences>(settings),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [editing, setEditing] = useState<CustomAgent | "new" | null>(null),
    [deleting, setDeleting] = useState<CustomAgent | null>(null);
  useEffect(() => setDraft(settings), [settings]);
  const profiles = useQuery(() => client.profiles(), [client]);
  const usage = useQuery(() => client.usage(), [client]);
  const location = useLocation(),
    navigate = useNavigate();
  const settingsKey = useRef(crypto.randomUUID());
  const update = <K extends keyof Preferences>(
    key: K,
    value: Preferences[K],
  ) => {
    settingsKey.current = crypto.randomUUID();
    setDraft((d) => ({ ...d, [key]: value }));
  };
  const save = async (next = false) => {
    setBusy(true);
    setError("");
    try {
      const s = await client.saveSettings(
        S.settings.parse({ ...draft, version: settings.version }),
        settingsKey.current,
      );
      setSettings(s);
      setDraft(s);
      notice("Preferences saved.");
      if (next) navigate("/simulations/new");
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Page
      eyebrow="MAKE YOURSELF AT HOME"
      title="Your way to see the world."
      description="A few personal touches. A little more possibility."
    >
      <div className="settings-layout">
        <div>
          <Section
            number="01"
            title="Look & feel"
            description="Settle into a perspective that feels right."
          >
            <span className="field-caption">APPEARANCE</span>
            <div className="appearance-options">
              <button
                className={draft.theme === "dark" ? "selected" : ""}
                onClick={() => update("theme", "dark")}
              >
                <div className="theme-preview dark-preview">
                  <i />
                  <i />
                  <i />
                </div>
                <span>
                  <Moon size={16} />
                  After hours{draft.theme === "dark" && <Check size={16} />}
                </span>
              </button>
              <button
                className={draft.theme === "light" ? "selected" : ""}
                onClick={() => update("theme", "light")}
              >
                <div className="theme-preview light-preview">
                  <i />
                  <i />
                  <i />
                </div>
                <span>
                  <Sun size={16} />
                  Daydream{draft.theme === "light" && <Check size={16} />}
                </span>
              </button>
            </div>
            <span className="field-caption">WORLD VIEW</span>
            <div className="segmented">
              <button
                className={draft.view_mode === "3d" ? "active" : ""}
                onClick={() => update("view_mode", "3d")}
              >
                <Box size={17} />
                3D city
              </button>
              <button
                className={draft.view_mode === "2d" ? "active" : ""}
                onClick={() => update("view_mode", "2d")}
              >
                <Map size={17} />
                2D map
              </button>
            </div>
            <label className="setting-toggle">
              <span>
                <strong>Reduced motion</strong>
                <small>Keep ambient animation and camera movement quiet.</small>
              </span>
              <input
                type="checkbox"
                checked={draft.reduce_motion}
                onChange={(e) => update("reduce_motion", e.target.checked)}
              />
            </label>
            <label className="setting-toggle">
              <span>
                <strong>Periodic autosave</strong>
                <small>
                  Save regular checkpoints. Navigation and event snapshots
                  always remain required.
                </small>
              </span>
              <input
                type="checkbox"
                checked={draft.autosave}
                onChange={(e) => update("autosave", e.target.checked)}
              />
            </label>
          </Section>
          <Section
            number="02"
            title="Familiar faces"
            description="Create citizens you can bring into future worlds."
          >
            <div className="section-toolbar">
              <p>Editing a template affects future citizens only.</p>
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
                <Users size={14} /> Start with a personality. Give them a story.
              </Empty>
            )}
          </Section>
          <Section
            number="03"
            title="At your fingertips"
            description="Shortcuts work only when the city viewport has focus."
          >
            <div className="shortcut-editor">
              {Object.entries(draft.shortcuts).map(([k, v]) => (
                <Field key={k} label={pretty(k)}>
                  <input
                    aria-label={`${pretty(k)} shortcut`}
                    value={v}
                    onChange={(e) =>
                      update("shortcuts", {
                        ...draft.shortcuts,
                        [k]: e.target.value,
                      })
                    }
                  />
                </Field>
              ))}
            </div>
            <p className="helper-text">
              <Keyboard size={14} />
              Use KeyboardEvent.code chords such as Mod+Equal or Shift+KeyR. Mod
              means Cmd on macOS and Ctrl elsewhere. Every shortcut must be
              unique.
            </p>
          </Section>
          {error && <ErrorBox error={error} />}
          <div className="form-footer">
            <Button
              kind="secondary"
              disabled={busy}
              onClick={() => void save()}
            >
              Save preferences
              <Check size={16} />
            </Button>
            <Button disabled={busy} onClick={() => void save(true)}>
              Save and continue
              <ArrowRight size={16} />
            </Button>
          </div>
          {location.state?.from?.startsWith("/simulations/") && (
            <Link className="back-link" to={location.state.from}>
              <ArrowRight size={14} />
              Return to your paused city
            </Link>
          )}
        </div>
        <aside className="settings-aside">
          <div className="eyebrow">
            <Activity size={13} /> MODEL USAGE
          </div>
          <h2>A little transparency.</h2>
          <p>
            Actual usage across your worlds. Historical playback makes no model
            calls.
          </p>
          {usage.error ? (
            <ErrorBox error={usage.error} />
          ) : !usage.data ? (
            <Busy />
          ) : (
            <>
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
          eyebrow="CUSTOM PROFILE"
          onClose={() => setDeleting(null)}
          busy={busy}
        >
          <p>
            This removes the saved template. Citizens already in a city keep
            their copied profile.
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
      title={
        existing
          ? "A new chapter for a familiar face."
          : "Every citizen starts with a story."
      }
      eyebrow="CUSTOM AGENT TEMPLATE"
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
            More of their story <ChevronDownIcon />
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
            {busy ? "Saving…" : "Save citizen profile"}
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
