import { useEffect, useState } from "react";
import cityImage from "../assets/city.png";

export type CityShot = { top: number; height: number; left: number };

// Alternating mirrored copies make every seam meet its own reflection.
export function CityTrack({ className = "" }: { className?: string }) {
  return (
    <div className={`city-track ${className}`}>
      {Array.from({ length: 8 }, (_, i) => (
        <img
          key={i}
          src={cityImage}
          alt=""
          draggable={false}
          className={i % 2 ? "mirrored" : ""}
        />
      ))}
    </div>
  );
}

const ZOOM_MS = 1100;
const FADE_MS = 750;

export function CityZoom({
  shot,
  onCovered,
  onDone,
}: {
  shot: CityShot;
  onCovered: () => void;
  onDone: () => void;
}) {
  const [phase, setPhase] = useState<"start" | "zoom" | "fade">("start");
  useEffect(() => {
    const raf = requestAnimationFrame(() =>
      requestAnimationFrame(() => setPhase("zoom")),
    );
    const covered = setTimeout(() => {
      onCovered();
      setPhase("fade");
    }, ZOOM_MS);
    const done = setTimeout(onDone, ZOOM_MS + FADE_MS);
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(covered);
      clearTimeout(done);
    };
  }, []);
  const vh = window.innerHeight;
  const center = shot.top + shot.height / 2;
  const scale = (vh / shot.height) * 2.4;
  return (
    <div className={`city-zoom ${phase}`} aria-hidden="true">
      <div
        className="city-zoom-stage"
        style={{
          top: shot.top,
          height: shot.height,
          transform:
            phase === "start"
              ? "none"
              : `translateY(${vh / 2 - center}px) scale(${scale})`,
        }}
      >
        <div className="city-zoom-offset" style={{ left: shot.left }}>
          <CityTrack />
        </div>
      </div>
    </div>
  );
}
