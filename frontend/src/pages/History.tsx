import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Archive,
  ArchiveRestore,
  GitBranch,
  Trash2,
  Plus,
  Users,
  Clock,
  Layers3,
} from "lucide-react";
import { useApp, useQuery, messageOf } from "../state/app";
import {
  Page,
  Button,
  Busy,
  ErrorBox,
  Empty,
  Modal,
  Field,
} from "../components/ui";
import { pretty, simTime } from "../api/defaults";
import {
  nameKey,
  simulationNames,
  takenMessage,
  uniqueName,
} from "../api/names";
import type { Simulation, WorldFrame } from "../api/types";
import { ComparePanel } from "../components/Drawer";
export default function History() {
  const { client, notice } = useApp();
  const navigate = useNavigate();
  const worlds = useQuery(async () => {
    const [active, archived] = await Promise.all([
      client.simulations(),
      client.simulations(true),
    ]);
    return { active, archived };
  }, [client]);
  const [selected, setSelected] = useState<string[]>([]),
    [deleting, setDeleting] = useState<Simulation[] | null>(null),
    [confirmations, setConfirmations] = useState<Record<string, string>>({}),
    [duplicating, setDuplicating] = useState<Simulation | null>(null),
    [compare, setCompare] = useState<WorldFrame | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const update = async (s: Simulation, type: "archive" | "unarchive") => {
    setBusy(true);
    setError("");
    try {
      await client.command(s, { type });
      worlds.reload();
      notice(
        type === "archive"
          ? "City paused, saved, and archived."
          : "City restored to active worlds, paused.",
      );
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!deleting) return;
    setBusy(true);
    setError("");
    const results = await Promise.allSettled(
      deleting.map((s) => client.delete(s)),
    );
    const failed = deleting.filter((_, i) => results[i].status === "rejected");
    const failures = results.filter(
      (r): r is PromiseRejectedResult => r.status === "rejected",
    );
    worlds.reload();
    setSelected([]);
    if (failed.length) {
      setDeleting(failed);
      setError(
        `${results.length - failed.length} deleted. ${failed.length} failed: ${failures.map((r) => messageOf(r.reason)).join(" ")}`,
      );
    } else {
      setDeleting(null);
      notice(
        `${results.length} archived ${results.length === 1 ? "world" : "worlds"} deleted.`,
      );
    }
    setBusy(false);
  };
  const card = (s: Simulation, archived = false) => (
    <article className={`world-card ${archived ? "archived" : ""}`} key={s.id}>
      <div className="world-card-art">
        <svg viewBox="0 0 300 95" aria-hidden="true">
          <path
            d="M0 85 110 25 300 85M40 95 140 38 270 95M80 95 150 56 230 95"
            fill="none"
            stroke="currentColor"
            opacity=".2"
          />
          {Array.from({ length: 8 }, (_, i) => (
            <path
              key={i}
              d={`M${55 + i * 24} ${70 + (i % 3) * 5}v-${15 + ((i * 13) % 35)}l12-6 12 6v${15 + ((i * 13) % 35)}l-12 6Z`}
              fill="currentColor"
              fillOpacity=".08"
              stroke="currentColor"
              strokeWidth=".8"
            />
          ))}
        </svg>
        {archived ? (
          <label className="card-checkbox">
            <input
              aria-label={`Select ${s.name}`}
              type="checkbox"
              checked={selected.includes(s.id)}
              onChange={(e) =>
                setSelected((ids) =>
                  e.target.checked
                    ? [...ids, s.id]
                    : ids.filter((id) => id !== s.id),
                )
              }
            />
          </label>
        ) : (
          <span className="pill">{pretty(s.config.mode)}</span>
        )}
        <span className={`pill ${s.status === "running" ? "green" : ""}`}>
          {pretty(s.status)}
        </span>
      </div>
      <div className="world-card-body">
        <small>
          {new Date(s.created_at).toLocaleString(undefined, {
            dateStyle: "medium",
            timeStyle: "short",
          })}
        </small>
        <h2>{s.name}</h2>
        <div className="world-meta">
          <span>
            <Users size={14} />
            {s.agent_count} citizens
          </span>
          <span>
            <Clock size={14} />
            {simTime(s.sim_time_seconds)}
          </span>
          <span>Tick {s.tick}</span>
        </div>
        <WorldMeasures simulation={s} />
        <div className="world-card-actions">
          <Button
            kind="secondary"
            disabled={busy}
            onClick={() =>
              navigate(
                `/simulations/${s.id}${s.status === "initializing" ? "/loading" : ""}`,
              )
            }
          >
            Open simulation
            <ArrowRight size={15} />
          </Button>
          <button
            className="icon-button"
            disabled={busy}
            aria-label={`Duplicate ${s.name}`}
            onClick={() => setDuplicating(s)}
          >
            <GitBranch size={17} />
          </button>
          <button
            className="icon-button"
            disabled={busy}
            aria-label={`Compare ${s.name}`}
            onClick={() => {
              setBusy(true);
              void client
                .state(s.id)
                .then(setCompare)
                .catch((e) => setError(messageOf(e)))
                .finally(() => setBusy(false));
            }}
          >
            <Layers3 size={17} />
          </button>
          <button
            className="icon-button"
            disabled={busy}
            aria-label={`${archived ? "Unarchive" : "Archive"} ${s.name}`}
            onClick={() => void update(s, archived ? "unarchive" : "archive")}
          >
            {archived ? <ArchiveRestore size={17} /> : <Archive size={17} />}
          </button>
        </div>
      </div>
    </article>
  );
  return (
    <Page
      title="Previous simulations"
      description="Open, duplicate, compare, archive, or delete the simulations you have created."
      action={
        <Link className="button primary" to="/simulations/new">
          <Plus size={16} />
          New simulation
        </Link>
      }
    >
      {error && !deleting && <ErrorBox error={error} />}{" "}
      {worlds.error ? (
        <ErrorBox error={worlds.error} retry={worlds.reload} />
      ) : !worlds.data ? (
        <Busy text="Finding your saved worlds…" />
      ) : (
        <>
          <div className="history-section-heading">
            <h2>
              Active simulations <span>{worlds.data.active.length}</span>
            </h2>
          </div>
          {worlds.data.active.length ? (
            <div className="world-grid">
              {worlds.data.active.map((s) => card(s))}
            </div>
          ) : (
            <Empty title="No simulations yet">
              Create a simulation and it will appear here.
            </Empty>
          )}
          <div className="history-section-heading archived-heading">
            <div>
              <h2>
                Archived simulations <span>{worlds.data.archived.length}</span>
              </h2>
            </div>
            {worlds.data.archived.length > 0 && (
              <Button
                kind="ghost"
                disabled={busy}
                onClick={() => {
                  setConfirmations({});
                  setError("");
                  setDeleting(
                    worlds.data!.archived.filter(
                      (s) => !selected.length || selected.includes(s.id),
                    ),
                  );
                }}
              >
                <Trash2 size={15} />
                {selected.length
                  ? `Delete selected (${selected.length})`
                  : "Permanently delete all"}
              </Button>
            )}
          </div>
          {worlds.data.archived.length ? (
            <div className="world-grid">
              {worlds.data.archived.map((s) => card(s, true))}
            </div>
          ) : (
            <p className="muted">No archived simulations.</p>
          )}
        </>
      )}
      {deleting && (
        <Modal
          title={`Permanently delete ${deleting.length} ${deleting.length === 1 ? "simulation" : "simulations"}?`}
          onClose={() => setDeleting(null)}
          busy={busy}
        >
          <p>
            Type each simulation’s exact name to confirm. Its stored history
            will be removed and cannot be recovered.
          </p>
          {deleting.map((s) => (
            <Field key={s.id} label={s.name}>
              <input
                value={confirmations[s.id] ?? ""}
                onChange={(e) =>
                  setConfirmations((c) => ({ ...c, [s.id]: e.target.value }))
                }
                placeholder={s.name}
              />
            </Field>
          ))}
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
              disabled={
                busy || deleting.some((s) => confirmations[s.id] !== s.name)
              }
              onClick={() => void remove()}
            >
              Permanently delete
            </Button>
          </div>
        </Modal>
      )}
      {duplicating && (
        <DuplicateDialog
          simulation={duplicating}
          onClose={() => setDuplicating(null)}
          onCreated={(id) => navigate(`/simulations/${id}`)}
        />
      )}{" "}
      {compare && (
        <Modal
          title="Compare branches"
          onClose={() => setCompare(null)}
          wide
        >
          <ComparePanel frame={compare} revision={compare.ref.revision} />
        </Modal>
      )}
    </Page>
  );
}
function WorldMeasures({ simulation: s }: { simulation: Simulation }) {
  const { client } = useApp();
  const r = useQuery(() => client.state(s.id, s.revision), [s.id, s.revision]);
  return (
    <div className="world-measures">
      {r.data ? (
        <>
          <span>{r.data.metrics.conflict_count} conflicts</span>
          <span>{r.data.metrics.resources_consumed} units consumed</span>
          <span>{r.data.events.length} major events</span>
          <span>
            {r.data.events.filter((e) => e.status === "resolved").length}{" "}
            outcomes
          </span>
        </>
      ) : r.error ? (
        <small>{r.error}</small>
      ) : (
        <span>Reading committed measures…</span>
      )}
    </div>
  );
}
function DuplicateDialog({
  simulation: s,
  onClose,
  onCreated,
}: {
  simulation: Simulation;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const { client } = useApp();
  const names = useQuery(() => simulationNames(client), [client]);
  const [name, setName] = useState(`${s.name.slice(0, 60)} copy`),
    [source, setSource] = useState("whole"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const key = useRef(crypto.randomUUID());
  const snapshots = useQuery(() => client.snapshots(s.id), [s.id]);
  const deduped = useRef(false);
  useEffect(() => {
    if (!names.data || deduped.current) return;
    deduped.current = true;
    setName((n) => uniqueName(n, names.data!));
  }, [names.data]);
  const nameTaken = !!names.data?.has(nameKey(name));
  const submit = async () => {
    setBusy(true);
    try {
      const r = await client.branch(
        s.id,
        name,
        source === "whole"
          ? { kind: "whole" }
          : { kind: "snapshot", snapshot_id: source },
        key.current,
      );
      onCreated(r.simulation.id);
    } catch (e) {
      setError(messageOf(e));
      setBusy(false);
    }
  };
  return (
    <Modal
      title="Duplicate simulation"
      onClose={onClose}
      busy={busy}
    >
      <p>
        Duplicate the whole simulation or start the copy from a saved point.
        The original stays unchanged.
      </p>
      <Field label="Name" error={nameTaken ? takenMessage : undefined}>
        <input
          maxLength={80}
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            key.current = crypto.randomUUID();
          }}
        />
      </Field>
      <Field label="Starting point">
        <select
          value={source}
          onChange={(e) => {
            setSource(e.target.value);
            key.current = crypto.randomUUID();
          }}
        >
          <option value="whole">Whole history through current head</option>
          {snapshots.data?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label} · tick {p.ref.tick} / rev {p.ref.revision}
            </option>
          ))}
        </select>
      </Field>
      {snapshots.error && <ErrorBox error={snapshots.error} />}{" "}
      {error && <ErrorBox error={error} />}
      <div className="modal-actions">
        <Button kind="ghost" disabled={busy} onClick={onClose}>
          Cancel
        </Button>
        <Button
          disabled={busy || !name.trim() || nameTaken}
          onClick={() => void submit()}
        >
          <GitBranch size={15} />
          Create paused copy
        </Button>
      </div>
    </Modal>
  );
}
