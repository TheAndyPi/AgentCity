/** Fit both citizens between the focus card and transcript, even while approaching. */
export function conversationCameraZoom(
  width: number,
  height: number,
  positions: { x: number; y: number }[],
) {
  const xs = positions.map((p) => p.x);
  const ys = positions.map((p) => p.y);
  // The camera looks across the pair, so diagonal separation is screen width too.
  const distance = Math.hypot(
    Math.max(...xs) - Math.min(...xs),
    Math.max(...ys) - Math.min(...ys),
  );
  const availableWidth = width > 760 ? Math.max(120, width - 700) : width * 0.8;
  const availableHeight = height * (width > 760 ? 0.64 : 0.3);
  return Math.min(72, Math.max(2, Math.min(availableWidth / (distance + 9), availableHeight / 9)));
}
