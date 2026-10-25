import { useEffect, useRef, useState, type SyntheticEvent } from "react";
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
import { calendarTime } from "../world/daylight";
import {
  nameKey,
  simulationNames,
  takenMessage,
  uniqueName,
} from "../api/names";
import type { Simulation, WorldFrame } from "../api/types";
import Drawer, { ComparePanel, type DrawerNode } from "../components/Drawer";
import { CityArt } from "../components/CityArt";
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
    [duplicating, setDuplicating] = useState<Simulation | null>(null),
    [compare, setCompare] = useState<WorldFrame | null>(null),
    [overview, setOverview] = useState<WorldFrame | null>(null),
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
  const confirmDelete = (saves: Simulation[]) => {
    setError("");
    setDeleting(saves);
  };
  const remove = async () => {
    if (!deleting) return;
    setBusy(true);
    setError("");
    const results = await Promise.allSettled(
      deleting.map(async (s) => {
        const current = await client.simulation(s.id);
        if (current.name !== s.name)
          throw new Error(
            `${s.name} was renamed. Refresh the list before deleting it.`,
          );
        if (!current.archived)
          await client.command(current, { type: "archive" });
        return client.delete(current);
      }),
    );
    const failed = deleting.filter((_, i) => results[i].status === "rejected");
    const failures = results.filter(
      (r): r is PromiseRejectedResult => r.status === "rejected",
    );
    worlds.reload();
    const removed = new Set(
      deleting
        .filter((_, i) => results[i].status === "fulfilled")
        .map((s) => s.id),
    );
    setSelected((ids) => ids.filter((id) => !removed.has(id)));
    if (failed.length) {
      setDeleting(failed);
      setError(
        `${results.length - failed.length} deleted. ${failed.length} failed: ${failures.map((r) => messageOf(r.reason)).join(" ")}`,
      );
    } else {
      setDeleting(null);
      notice(
        `${results.length} ${results.length === 1 ? "save" : "saves"} deleted.`,
      );
    }
    setBusy(false);
  };
  const archiveSelected = async () => {
    const targets = worlds.data!.active.filter((s) => selected.includes(s.id));
    setBusy(true);
    setError("");
    const results = await Promise.allSettled(
      targets.map((s) => client.command(s, { type: "archive" })),
    );
    const failures = results.filter(
      (r): r is PromiseRejectedResult => r.status === "rejected",
    );
    setSelected((ids) =>
      ids.filter(
        (id) =>
          !targets.some(
            (s, i) => s.id === id && results[i].status === "fulfilled",
          ),
      ),
    );
    worlds.reload();
    if (failures.length)
      setError(
        `${results.length - failures.length} archived. ${failures.length} failed: ${failures.map((r) => messageOf(r.reason)).join(" ")}`,
      );
    else
      notice(
        `${results.length} ${results.length === 1 ? "city" : "cities"} paused, saved, and archived.`,
      );
    setBusy(false);
  };
  const toggle = (id: string, on: boolean) =>
    setSelected((ids) => (on ? [...ids, id] : ids.filter((x) => x !== id)));
  const card = (s: Simulation, archived = false) => (
    <WorldCard
      key={s.id}
      simulation={s}
      archived={archived}
      busy={busy}
      selected={selected.includes(s.id)}
      onSelect={(on) => toggle(s.id, on)}
      onOpen={() =>
        navigate(
          `/simulations/${s.id}${s.status === "initializing" ? "/loading" : ""}`,
        )
      }
      onDuplicate={() => setDuplicating(s)}
      onCompare={() => {
        setBusy(true);
        void client
          .state(s.id)
          .then(setCompare)
          .catch((e) => setError(messageOf(e)))
          .finally(() => setBusy(false));
      }}
      onArchive={() => void update(s, archived ? "unarchive" : "archive")}
      onDelete={() => confirmDelete([s])}
      onOverview={setOverview}
    />
  );
  const activeSelected = worlds.data
    ? worlds.data.active.filter((s) => selected.includes(s.id)).length
    : 0;
  const saves = worlds.data
    ? [...worlds.data.active, ...worlds.data.archived]
    : [];
  const selectedSaves = saves.filter((s) => selected.includes(s.id));
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
          {saves.length > 0 && (
            <div className="history-selection-bar">
              <label>
                <input
                  type="checkbox"
                  checked={selectedSaves.length === saves.length}
                  disabled={busy}
                  onChange={(e) =>
                    setSelected(e.target.checked ? saves.map((s) => s.id) : [])
                  }
                />
                Select all saves
              </label>
              <span>{selectedSaves.length} selected</span>
              <Button
                kind="danger"
                disabled={busy || selectedSaves.length === 0}
                onClick={() => confirmDelete(selectedSaves)}
              >
                <Trash2 size={15} />
                Delete selected
                {selectedSaves.length > 0 && ` (${selectedSaves.length})`}
              </Button>
            </div>
          )}
          <div className="history-section-heading">
            <h2>
              Active simulations <span>{worlds.data.active.length}</span>
            </h2>
            {activeSelected > 0 && (
              <Button
                kind="ghost"
                disabled={busy}
                onClick={() => void archiveSelected()}
              >
                <Archive size={15} />
                Archive selected ({activeSelected})
              </Button>
            )}
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
                onClick={() => confirmDelete(worlds.data!.archived)}
              >
                <Trash2 size={15} />
                Delete all archived
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
          title={`Delete ${deleting.length === 1 ? "saved simulation" : `${deleting.length} saved simulations`}?`}
          onClose={() => setDeleting(null)}
          busy={busy}
        >
          <p>
            These saves and their history will be permanently deleted. This
            cannot be undone.
          </p>
          <ul className="delete-save-list">
            {deleting.map((s) => (
              <li key={s.id}>{s.name}</li>
            ))}
          </ul>
          {error && <ErrorBox error={error} />}
          <div className="modal-actions">
            <Button
              kind="ghost"
              disabled={busy}
              onClick={() => setDeleting(null)}
            >
              Cancel
            </Button>
            <Button kind="danger" disabled={busy} onClick={() => void remove()}>
              {busy
                ? "Deleting…"
                : deleting.length === 1
                  ? "Delete save"
                  : `Delete ${deleting.length} saves`}
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
        <Modal title="Compare branches" onClose={() => setCompare(null)} wide>
          <ComparePanel frame={compare} revision={compare.ref.revision} />
        </Modal>
      )}
      {overview && (
        <OverviewCard frame={overview} onClose={() => setOverview(null)} />
      )}
    </Page>
  );
}
function WorldCard({
  simulation: s,
  archived,
  busy,
  selected,
  onSelect,
  onOpen,
  onDuplicate,
  onCompare,
  onArchive,
  onDelete,
  onOverview,
}: {
  simulation: Simulation;
  archived: boolean;
  busy: boolean;
  selected: boolean;
  onSelect: (on: boolean) => void;
  onOpen: () => void;
  onDuplicate: () => void;
  onCompare: () => void;
  onArchive: () => void;
  onDelete: () => void;
  onOverview: (frame: WorldFrame) => void;
}) {
  const { client } = useApp();
  const card = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!card.current) return;
    if (typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(card.current);
    return () => observer.disconnect();
  }, []);
  const r = useQuery(
    () => (visible ? client.state(s.id, s.revision) : Promise.resolve(null)),
    [s.id, s.revision, visible],
  );
  const open = (e: SyntheticEvent) => {
    if (
      (e.target as HTMLElement).closest(
        "button, a, input, label, select, textarea",
      )
    )
      return;
    if (r.data) onOverview(r.data);
  };
  return (
    <article
      ref={card}
      className={`world-card ${archived ? "archived" : ""} ${selected ? "selected" : ""}`}
      tabIndex={0}
      aria-label={`${s.name}. Open the simulation overview`}
      onClick={open}
      onKeyDown={(e) => {
        if (
          (e.key === "Enter" || e.key === " ") &&
          e.target === e.currentTarget
        ) {
          e.preventDefault();
          open(e);
        }
      }}
    >
      <div className="world-card-art">
        {r.data ? (
          <CityArt map={r.data.map} />
        ) : (
          <span className="city-art-pending" />
        )}
        <span className="pill">{pretty(s.config.mode)}</span>
        {(s.status === "initializing" ||
          s.status === "failed" ||
          s.status === "completed") && (
          <span className="pill status-pill">{pretty(s.status)}</span>
        )}
        <label className="card-checkbox">
          <input
            aria-label={`Select ${s.name}`}
            type="checkbox"
            checked={selected}
            disabled={busy}
            onChange={(e) => onSelect(e.target.checked)}
          />
        </label>
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
            {simTime(calendarTime(s))}
          </span>
          <span>Tick {s.tick}</span>
        </div>
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
        <div className="world-card-actions">
          <Button kind="secondary" disabled={busy} onClick={onOpen}>
            Open simulation
            <ArrowRight size={15} />
          </Button>
          <button
            className="icon-button"
            disabled={busy}
            aria-label={`Duplicate ${s.name}`}
            onClick={onDuplicate}
          >
            <GitBranch size={17} />
          </button>
          <button
            className="icon-button"
            disabled={busy}
            aria-label={`Compare ${s.name}`}
            onClick={onCompare}
          >
            <Layers3 size={17} />
          </button>
          <button
            className="icon-button"
            disabled={busy}
            aria-label={`${archived ? "Unarchive" : "Archive"} ${s.name}`}
            onClick={onArchive}
          >
            {archived ? <ArchiveRestore size={17} /> : <Archive size={17} />}
          </button>
          <button
            className="button ghost world-card-delete"
            disabled={busy}
            aria-label={`Delete ${s.name}`}
            onClick={onDelete}
          >
            <Trash2 size={15} />
            Delete save
          </button>
        </div>
      </div>
    </article>
  );
}
function OverviewCard({
  frame,
  onClose,
}: {
  frame: WorldFrame;
  onClose: () => void;
}) {
  const [stack, setStack] = useState<DrawerNode[]>([{ type: "overview" }]);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close.current();
      }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, []);
  return (
    <div
      className="modal-backdrop overview-popup"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <Drawer
        stack={stack}
        frame={frame}
        revision={frame.ref.revision}
        readOnly
        onPush={(n) => setStack((s) => [...s, n])}
        onBack={() =>
          stack.length > 1 ? setStack((s) => s.slice(0, -1)) : onClose()
        }
        onClose={onClose}
        onCommand={async () => {}}
        follow={null}
        setFollow={() => {}}
      />
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
  const events = useQuery(() => client.events(s.id), [s.id]);
  const beforeEvent = new Map(
    (events.data ?? []).map((e) => [e.pre_event_snapshot_id, e.title]),
  );
  const points = (snapshots.data ?? [])
    .map((p) => ({
      ...p,
      event:
        beforeEvent.get(p.id) ??
        (p.reason === "pre_event" ? p.label.replace(/^Before /, "") : null),
    }))
    .sort(
      (a, b) =>
        Number(!a.event) - Number(!b.event) || a.ref.revision - b.ref.revision,
    );
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
    <Modal title="Duplicate simulation" onClose={onClose} busy={busy}>
      <p>
        Duplicate the whole simulation or start the copy from a saved point. The
        original stays unchanged.
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
          {points.some((p) => p.event) && (
            <optgroup label="Before a major event">
              {points
                .filter((p) => p.event)
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    Right before {p.event} · tick {p.ref.tick}
                  </option>
                ))}
            </optgroup>
          )}
          {points.some((p) => !p.event) && (
            <optgroup label="Saved points">
              {points
                .filter((p) => !p.event)
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label} · tick {p.ref.tick} / rev {p.ref.revision}
                  </option>
                ))}
            </optgroup>
          )}
        </select>
      </Field>
      {(snapshots.error || events.error) && (
        <ErrorBox error={snapshots.error || events.error} />
      )}{" "}
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
