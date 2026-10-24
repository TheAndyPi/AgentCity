/** Remove the listener before renderer disposal, which can intentionally lose its context. */
export function subscribeToContextLoss(
  target: EventTarget,
  onLoss: () => void,
) {
  const lost = (event: Event) => {
    event.preventDefault();
    onLoss();
  };
  target.addEventListener("webglcontextlost", lost);
  return () => target.removeEventListener("webglcontextlost", lost);
}
