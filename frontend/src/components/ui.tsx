import { useEffect, useId, useRef, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  ArrowLeft,
  ArrowUpRight,
  ChevronRight,
  LoaderCircle,
  X,
  Activity,
} from "lucide-react";
export function Brand({ large = false }: { large?: boolean }) {
  return (
    <span className={`brand ${large ? "brand-large" : ""}`}>
      <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
        <path
          d="M5 38V23l10-6v21m0-9 9-5v14m0-27 11-6v33m0-17 8 5v12M2 39h44M9 25v4m10 2v3m9-19v4m0 5v4m11 0v5"
          stroke="currentColor"
          strokeWidth="1.4"
        />
      </svg>
      <span>
        AGENT<span className="brand-city">CITY</span>
      </span>
    </span>
  );
}
export function Ambient() {
  return (
    <div className="ambient" aria-hidden="true">
      <div className="ambient-orb" />
      <svg
        className="ambient-circuit"
        viewBox="0 0 1440 900"
        preserveAspectRatio="xMidYMid slice"
      >
        <path d="M0 140h210l70 70h140l70-70h240l90 90h100l90-90h330M0 690h170l80-80h220l80 80h180l70-70h190l100 100h350M90 0v220l80 80v200l-80 80v320M1320 0v150l-80 80v360l80 80v230" />
        <circle cx="420" cy="210" r="5" />
        <circle cx="990" cy="620" r="5" />
      </svg>
      <div className="gear gear-one">⚙</div>
      <div className="gear gear-two">⚙</div>
    </div>
  );
}
export function Page({
  eyebrow,
  title,
  description,
  children,
  action,
}: {
  eyebrow: string;
  title: string;
  description?: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  const location = useLocation();
  return (
    <div className="page">
      <Ambient />
      <header className="site-header">
        <Link to="/" aria-label="AgentCity home">
          <Brand />
        </Link>
        <nav>
          <Link to="/simulations">Your worlds</Link>
          <Link to="/settings">Settings</Link>
          <Link to="/about">
            About <ArrowUpRight size={14} />
          </Link>
        </nav>
      </header>
      <main className="page-content">
        <Link
          className="back-link"
          to={(location.state as { from?: string })?.from ?? "/"}
        >
          <ArrowLeft size={15} /> Back
        </Link>
        <div className="page-heading">
          <div>
            <div className="eyebrow">{eyebrow}</div>
            <h1>{title}</h1>
            {description && <p>{description}</p>}
          </div>
          {action}
        </div>
        {children}
      </main>
      <footer className="site-footer">
        <span>
          <Activity size={13} /> A world of what ifs.
        </span>
        <span>AGENTCITY / EXPERIMENT WITH POSSIBILITY</span>
      </footer>
    </div>
  );
}
export function Button({
  children,
  onClick,
  disabled = false,
  kind = "primary",
  type = "button",
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  kind?: "primary" | "secondary" | "ghost" | "danger";
  type?: "button" | "submit";
  className?: string;
}) {
  return (
    <button
      type={type}
      className={`button ${kind} ${className}`}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}
export function ErrorBox({
  error,
  retry,
}: {
  error: string;
  retry?: () => void;
}) {
  return (
    <div className="error-box" role="alert">
      <strong>Something needs your attention</strong>
      <p>{error}</p>
      {retry && (
        <Button kind="secondary" onClick={retry}>
          Try again
        </Button>
      )}
    </div>
  );
}
export function Busy({ text = "Loading…" }: { text?: string }) {
  return (
    <div className="busy" role="status">
      <LoaderCircle size={20} className="spin" />
      {text}
    </div>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <Activity size={26} />
      <h3>{title}</h3>
      {children && <p>{children}</p>}
    </div>
  );
}
export function Modal({
  title,
  eyebrow,
  children,
  onClose,
  busy = false,
  wide = false,
  dismissible = true,
}: {
  title: string;
  eyebrow?: string;
  children: ReactNode;
  onClose: () => void;
  busy?: boolean;
  wide?: boolean;
  dismissible?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const busyRef = useRef(busy);
  busyRef.current = busy;
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        if (!busyRef.current && dismissible) closeRef.current();
      }
      if (e.key === "Tab") {
        const nodes = ref.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href],[tabindex="0"]',
        );
        if (!nodes?.length) {
          e.preventDefault();
          return;
        }
        const first = nodes[0],
          last = nodes[nodes.length - 1];
        if (
          e.shiftKey &&
          (document.activeElement === first ||
            document.activeElement === ref.current)
        ) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", key, true);
    return () => {
      document.removeEventListener("keydown", key, true);
      opener?.focus();
    };
  }, []);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy && dismissible) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        ref={ref}
        className={`modal ${wide ? "wide" : ""}`}
      >
        <header>
          <div>
            {eyebrow && <div className="eyebrow">{eyebrow}</div>}
            <h2 id={titleId}>{title}</h2>
          </div>
          <button
            className="icon-button"
            aria-label="Close dialog"
            disabled={busy || !dismissible}
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </header>
        {children}
      </div>
    </div>
  );
}
export function Field({
  label,
  children,
  hint,
  error,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
  error?: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
      {error && (
        <small className="field-error" role="alert">
          {error}
        </small>
      )}
    </label>
  );
}
export function Slider({
  label,
  value,
  onChange,
  min = 0,
  max = 100,
  hint,
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
  min?: number;
  max?: number;
  hint?: string;
}) {
  const inputId = useId();
  return (
    <label className="slider-field" htmlFor={inputId}>
      <span>
        {label}
        <output>
          {value}
          {max === 100 ? "%" : ""}
        </output>
      </span>
      <input
        id={inputId}
        aria-label={label}
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      {hint && <small>{hint}</small>}
    </label>
  );
}
export function Section({
  number,
  title,
  description,
  children,
}: {
  number: string;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="form-section">
      <div className="section-heading">
        <span className="section-number">{number}</span>
        <div>
          <h2>{title}</h2>
          {description && <p>{description}</p>}
        </div>
      </div>
      {children}
    </section>
  );
}
export function Arrow() {
  return <ChevronRight size={17} />;
}
