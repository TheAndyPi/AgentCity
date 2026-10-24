import {
  useEffect,
  useId,
  useRef,
  type CSSProperties,
  type ReactNode,
} from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { ArrowLeft, ChevronRight, LoaderCircle, X, Activity } from "lucide-react";
import gearImage from "../assets/gear.png";
import wiresImage from "../assets/wires.png";
export function CityMark({ className = "" }: { className?: string }) {
  return (
    <svg
      className={`city-mark ${className}`}
      viewBox="0 0 48 40"
      fill="none"
      aria-hidden="true"
    >
      <g
        stroke="currentColor"
        strokeWidth="1.1"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M2 37V16h6l3 2v19M8 16v21M2 22l6 4M8 22l-6 5M2 31l6 3M11 24l-3 3" />
        <path d="M14 37V11l5-2 5 2v26M19 9v28M19 9V2M14 17l5 3 5-3M14 25l5-3 5 4M14 32l5 2 5-3" />
        <path d="M27 37V18h5l3 2v17M32 18v19M30 18v-5M27 24l5 3M32 24l3 4M27 31l5-2 3 3" />
        <path d="M38 37V26l4-1.5 4 1.5v11M42 24.5V37M38 31l4 2 4-2" />
        <path d="M1 37.5h46" opacity=".5" />
      </g>
      <circle cx="19" cy="2" r="1.3" className="mark-dot pink" />
      <circle cx="30" cy="13" r="1.1" className="mark-dot yellow" />
      <circle cx="42" cy="24.5" r="1" className="mark-dot green" />
    </svg>
  );
}
export function Brand({ large = false }: { large?: boolean }) {
  return (
    <span className={`brand ${large ? "brand-large" : ""}`}>
      <CityMark />
      <span>
        AGENT<span className="brand-city">CITY</span>
      </span>
    </span>
  );
}
const random = (seed: number) => {
  const x = Math.sin(seed * 9301 + 49297) * 233280;
  return x - Math.floor(x);
};
export function Ambient({ variant = "default" }: { variant?: "default" | "settings" }) {
  const count = variant === "settings" ? 16 : 9;
  const [minSize, maxSize] = variant === "settings" ? [140, 460] : [70, 240];
  const gears = Array.from({ length: count }, (_, i) => {
    const size = minSize + random(i + 1) * (maxSize - minSize);
    return (
      <img
        key={i}
        src={gearImage}
        alt=""
        className={`ambient-gear tint-${i % 4}`}
        style={{
          width: size,
          height: size,
          left: `${random(i + 11) * 100}%`,
          top: `${random(i + 23) * 100}%`,
          animationDuration: `${60 + random(i + 37) * 90}s`,
          animationDirection: i % 2 ? "reverse" : "normal",
        }}
      />
    );
  });
  return (
    <div className={`ambient ambient-${variant}`} aria-hidden="true">
      <div
        className="ambient-wires"
        style={{ backgroundImage: `url(${wiresImage})` }}
      />
      <div
        className="ambient-wires ambient-wires-flip"
        style={{ backgroundImage: `url(${wiresImage})` }}
      />
      {gears}
    </div>
  );
}
export function Page({
  title,
  description,
  children,
  action,
  ambient = "default",
}: {
  title: string;
  description?: string;
  children: ReactNode;
  action?: ReactNode;
  ambient?: "default" | "settings";
}) {
  const location = useLocation();
  return (
    <div className="page">
      <Ambient variant={ambient} />
      <header className="site-header">
        <Link to="/" aria-label="AgentCity home">
          <Brand />
        </Link>
        <nav aria-label="Main">
          <NavLink to="/simulations" end>
            Previous simulations
          </NavLink>
          <NavLink to="/templates">Common simulations</NavLink>
          <NavLink to="/settings">Settings</NavLink>
          <NavLink to="/about">About</NavLink>
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
            <h1>{title}</h1>
            {description && <p>{description}</p>}
          </div>
          {action}
        </div>
        {children}
      </main>
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
  const share = max > min ? (value - min) / (max - min) : 0;
  return (
    <label className="slider-field" htmlFor={inputId}>
      <span>
        {label}
        <output>
          {value}
          {max === 100 ? "%" : ""}
        </output>
      </span>
      <span
        className="gear-range"
        style={{ "--share": share } as CSSProperties}
      >
        <span className="gear-range-track">
          <span className="gear-range-fill" />
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
        <span className="gear-range-knob">
          <img
            src={gearImage}
            alt=""
            style={{ transform: `rotate(${share * 360}deg)` }}
          />
        </span>
      </span>
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
