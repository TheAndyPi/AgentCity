import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowUpRight,
  ArrowRight,
  Layers3,
  SlidersHorizontal,
  Info,
  History,
  MoveUpRight,
} from "lucide-react";
import { Brand } from "../components/ui";
import { useApp } from "../state/app";
export function WireCity() {
  const buildings = Array.from({ length: 46 }, (_, i) => {
    const col = i % 10,
      row = Math.floor(i / 10);
    const x = 310 + (col - row) * 58,
      y = 265 + (col + row) * 23,
      h = 30 + ((i * 37) % 105),
      w = 34,
      d = 17;
    return (
      <g
        key={i}
        className="wire-building"
        style={{ animationDelay: `${i * -0.3}s` }}
      >
        <path
          d={`M${x} ${y}v-${h}l${w} -${d} ${w} ${d}v${h}l-${w} ${d}Z M${x} ${y - h}l${w} ${d} ${w}-${d} M${x + w} ${y - h + d}v${h}`}
        />
        {Array.from({ length: Math.floor(h / 18) }, (_, j) => (
          <path
            key={j}
            opacity=".45"
            d={`M${x + 6} ${y - h + 16 + j * 16}l23 11 M${x + w + 6} ${y - h + 24 + j * 16}l23-11`}
          />
        ))}
      </g>
    );
  });
  return (
    <svg
      className="wire-city"
      viewBox="0 0 1200 700"
      fill="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="cityfade" x1="0" y1="0" x2="0" y2="1">
          <stop stopColor="#c4a1ff" />
          <stop offset="1" stopColor="#6d58a1" stopOpacity=".2" />
        </linearGradient>
        <radialGradient id="ground-glow">
          <stop stopColor="#b58bff" stopOpacity=".2" />
          <stop offset="1" stopColor="#b58bff" stopOpacity="0" />
        </radialGradient>
      </defs>
      <ellipse cx="600" cy="450" rx="580" ry="220" fill="url(#ground-glow)" />
      <g stroke="#6f5b93" strokeWidth=".55" opacity=".35">
        {Array.from({ length: 23 }, (_, i) => (
          <path
            key={i}
            d={`M${i * 65 - 300} 700 600 210 ${i * 65 + 500} 700`}
          />
        ))}
        {Array.from({ length: 12 }, (_, i) => (
          <path
            key={i}
            d={`M${300 - i * 60} ${260 + i * 36}H${900 + i * 60}`}
          />
        ))}
      </g>
      <g stroke="url(#cityfade)" strokeWidth="1.2">
        {buildings}
      </g>
      <g stroke="#81efdb" opacity=".8">
        <path className="signal" d="m220 456 220 88 188-80 180 70 180-74" />
        <circle cx="440" cy="544" r="4" fill="#81efdb" />
        <circle cx="808" cy="534" r="4" fill="#bca2ff" />
      </g>
    </svg>
  );
}
export default function Landing() {
  const navigate = useNavigate();
  const { settings, client } = useApp();
  const [zoom, setZoom] = useState(false);
  const start = () => {
    setZoom(true);
    setTimeout(
      () => navigate("/simulations/new"),
      settings.reduce_motion ? 0 : 400,
    );
  };
  return (
    <div className={`landing ${zoom ? "wire-zoom" : ""}`}>
      <div className="landing-grid" />
      <div className="landing-glow" />
      <header className="landing-header">
        <Link to="/" aria-label="AgentCity home">
          <Brand />
        </Link>
        <span className="landing-tag">
          <span /> A LIVING SOCIAL SIMULATION
        </span>
        <Link className="header-link" to="/about">
          Inside the experiment <ArrowUpRight size={15} />
        </Link>
      </header>
      <main className="landing-main">
        <div className="landing-eyebrow">
          <span className="tiny-line" /> SMALL WORLD. INFINITE POSSIBILITIES.
        </div>
        <h1>
          AGENT<span>CITY</span>
          <span className="title-star">✳</span>
        </h1>
        <p className="landing-subtitle">
          Every citizen has a story.
          <br />
          Every choice changes the city.
        </p>
        <p className="landing-description">
          Create a living society. Introduce the unexpected.
          <br />
          Discover what happens when people come together.
        </p>
        <div className="landing-actions">
          <button className="button primary start-button" onClick={start}>
            Start custom simulation <ArrowRight size={18} />
          </button>
          {client.mode === "mock" && (
            <Link className="demo-link" to="/simulations/preview-eden">
              Explore the preview city <MoveUpRight size={14} />
            </Link>
          )}
        </div>
        <div className="landing-proof">
          <span>
            <i />
            Autonomous citizens
          </span>
          <span>
            <i />
            Persistent memories
          </span>
          <span>
            <i />
            Emergent stories
          </span>
        </div>
      </main>
      <div className="landing-art">
        <WireCity />
        <div className="city-coordinate">40° 42′ N / A CITY OF POSSIBILITY</div>
        <div className="city-label">
          <span /> New connections are taking shape
        </div>
      </div>
      <div className="landing-bottom">
        <nav className="floating-menu" aria-label="Explore AgentCity">
          {[
            {
              to: "/simulations",
              icon: History,
              label: "Previous simulations",
            },
            { to: "/templates", icon: Layers3, label: "Common simulations" },
            { to: "/settings", icon: SlidersHorizontal, label: "Settings" },
            { to: "/about", icon: Info, label: "About" },
          ].map(({ to, icon: Icon, label }) => (
            <Link key={to} to={to}>
              <Icon size={18} />
              <span>{label}</span>
              <ArrowUpRight className="menu-arrow" size={14} />
            </Link>
          ))}
        </nav>
        <span className="landing-footnote">A SANDBOX FOR THE CURIOUS.</span>
        <span className="version-label">
          AGENTCITY <span>01 / 2026</span>
        </span>
      </div>
    </div>
  );
}
