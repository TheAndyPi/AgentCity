import { useRef, useState, type CSSProperties } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, Layers3, SlidersHorizontal, Info, History } from "lucide-react";
import { Brand } from "../components/ui";
import { CityTrack } from "../components/CityStrip";
import { useApp } from "../state/app";

const lightColors = ["pink", "yellow", "cyan", "green"];
const random = (seed: number) => {
  const x = Math.sin(seed * 7919 + 104729) * 15485863;
  return x - Math.floor(x);
};
const lights = Array.from({ length: 46 }, (_, i) => ({
  left: random(i + 1) * 100,
  top: random(i + 101) * 58,
  size: 2 + random(i + 201) * 4,
  color: lightColors[i % lightColors.length],
  duration: 4 + random(i + 301) * 6,
  delay: -random(i + 401) * 10,
}));

export default function Landing() {
  const navigate = useNavigate();
  const { settings, client, zoomCity } = useApp();
  const [leaving, setLeaving] = useState(false);
  const strip = useRef<HTMLDivElement>(null),
    track = useRef<HTMLDivElement>(null);
  const start = () => {
    if (leaving) return;
    const go = () => navigate("/simulations/new");
    if (settings.reduce_motion || !strip.current || !track.current) {
      go();
      return;
    }
    const rect = strip.current.getBoundingClientRect();
    const offset = new DOMMatrixReadOnly(
      getComputedStyle(track.current).transform,
    ).m41;
    setLeaving(true);
    zoomCity({ top: rect.top, height: rect.height, left: offset }, go);
  };
  return (
    <div className={`home ${leaving ? "leaving" : ""}`}>
      <div className="home-lights" aria-hidden="true">
        {lights.map((l, i) => (
          <i
            key={i}
            className={l.color}
            style={
              {
                left: `${l.left}%`,
                top: `${l.top}%`,
                width: l.size,
                height: l.size,
                animationDuration: `${l.duration}s`,
                animationDelay: `${l.delay}s`,
              } as CSSProperties
            }
          />
        ))}
      </div>
      <header className="home-header">
        <Link to="/" aria-label="AgentCity home">
          <Brand />
        </Link>
      </header>
      <main className="home-main">
        <h1>
          AGENT <span>CITY</span>
        </h1>
        <p className="home-description">
          Build a town of AI citizens, introduce events, and watch how they
          respond.
        </p>
        <div className="home-actions">
          <button className="button primary home-start" onClick={start}>
            Build custom simulation <ArrowRight size={18} />
          </button>
          {client.mode === "mock" && (
            <Link className="home-demo" to="/simulations/preview-eden">
              Open the preview city
            </Link>
          )}
        </div>
      </main>
      <div className="home-city" ref={strip} aria-hidden="true">
        <div className="home-city-scroll" ref={track}>
          <CityTrack />
        </div>
      </div>
      <nav className="home-nav" aria-label="Explore AgentCity">
        {[
          { to: "/simulations", icon: History, label: "Previous simulations" },
          { to: "/templates", icon: Layers3, label: "Common simulations" },
          { to: "/settings", icon: SlidersHorizontal, label: "Settings" },
          { to: "/about", icon: Info, label: "About" },
        ].map(({ to, icon: Icon, label }) => (
          <Link key={to} to={to}>
            <Icon size={17} />
            <span>{label}</span>
          </Link>
        ))}
      </nav>
    </div>
  );
}
