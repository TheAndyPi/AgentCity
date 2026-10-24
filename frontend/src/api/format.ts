export function metricDelta(value: number) {
  if (Math.abs(value) < 1e-10) return "0.00";
  const magnitude = Math.abs(value);
  return `${value > 0 ? "+" : "−"}${magnitude < 0.005 ? "<0.01" : magnitude.toFixed(2)}`;
}
