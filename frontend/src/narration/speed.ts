import type { Simulation } from "../api/types";

export type Clock = Pick<Simulation, "id" | "status" | "speed_multiplier">;

export async function slowForConversation(
  current: () => Clock | null,
  setSpeed: (value: Simulation["speed_multiplier"]) => Promise<void>,
) {
  const before = current();
  if (!before || before.status !== "running" || before.speed_multiplier <= 0.25)
    return;
  const previousSpeed = before.speed_multiplier;
  await setSpeed(0.25);
  return async () => {
    const after = current();
    if (after?.id === before.id && after.speed_multiplier === 0.25)
      await setSpeed(previousSpeed);
  };
}
