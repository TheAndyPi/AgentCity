import { useEffect, useRef } from "react";

type Point = { x: number; y: number; t: number };

const LIFETIME = 380;
const MIN_SPEED = 0.9;

export function MouseTrail({ enabled }: { enabled: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const el = canvas.current;
    if (!enabled || !el) return;
    const ctx = el.getContext("2d");
    if (!ctx) return;
    let points: Point[] = [];
    let last: Point | null = null;
    let frame = 0;
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      el.width = window.innerWidth * dpr;
      el.height = window.innerHeight * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    const draw = () => {
      const now = performance.now();
      points = points.filter((p) => now - p.t < LIFETIME);
      ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      for (let i = 1; i < points.length; i++) {
        const a = points[i - 1],
          b = points[i];
        if (!a || !b) continue;
        const life = 1 - (now - b.t) / LIFETIME;
        ctx.strokeStyle = `rgba(120, 236, 255, ${life * 0.85})`;
        ctx.shadowColor = "rgba(80, 220, 255, 0.9)";
        ctx.shadowBlur = 12 * life;
        ctx.lineWidth = 0.6 + 2.4 * life;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }
      frame = points.length ? requestAnimationFrame(draw) : 0;
    };
    const move = (e: PointerEvent) => {
      if (e.pointerType === "touch") return;
      const point = { x: e.clientX, y: e.clientY, t: performance.now() };
      if (last) {
        const speed =
          Math.hypot(point.x - last.x, point.y - last.y) /
          Math.max(1, point.t - last.t);
        if (speed > MIN_SPEED) {
          if (points[points.length - 1] !== last) points.push(last);
          points.push(point);
          if (!frame) frame = requestAnimationFrame(draw);
        }
      }
      last = point;
    };
    resize();
    window.addEventListener("resize", resize);
    window.addEventListener("pointermove", move, { passive: true });
    return () => {
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", move);
      cancelAnimationFrame(frame);
      ctx.clearRect(0, 0, el.width, el.height);
    };
  }, [enabled]);
  if (!enabled) return null;
  return <canvas ref={canvas} className="mouse-trail" aria-hidden="true" />;
}
