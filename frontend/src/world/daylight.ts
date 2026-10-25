import type { Simulation, WorldFrame } from "../api/types";

export const calendarTime = (simulation: Simulation) =>
  simulation.calendar_time_seconds ?? simulation.sim_time_seconds;

export function dayPhase(seconds: number) {
  const hour = (((seconds % 86400) + 86400) % 86400) / 3600;
  if (hour >= 5 && hour < 7) return "Dawn";
  if (hour >= 7 && hour < 19) return "Day";
  if (hour >= 19 && hour < 21) return "Dusk";
  return "Night";
}

export function daylight(seconds: number) {
  const hour = (((seconds % 86400) + 86400) % 86400) / 3600;
  if (hour >= 5 && hour < 7) return (hour - 5) / 2;
  if (hour >= 7 && hour < 19) return 1;
  if (hour >= 19 && hour < 21) return (21 - hour) / 2;
  return 0;
}

export const clockTime = (seconds: number) =>
  `${String(Math.floor(seconds / 3600) % 24).padStart(2, "0")}:${String(Math.floor(seconds / 60) % 60).padStart(2, "0")}`;

export function curfewActive(frame: WorldFrame) {
  const policy = frame.curfew;
  if (!policy?.enabled) return false;
  const minute = Math.floor(calendarTime(frame.simulation) / 60) % 1440;
  return policy.start_minute < policy.end_minute
    ? minute >= policy.start_minute && minute < policy.end_minute
    : minute >= policy.start_minute || minute < policy.end_minute;
}

export function activityLabel(
  agent: WorldFrame["agents"][number],
  frame?: WorldFrame,
) {
  const session = frame?.conversation_sessions?.find(
    (session) =>
      session.status === "accepted" &&
      session.participant_ids.includes(agent.id),
  );
  if (session || agent.routine_state === "talking" || agent.action === "talk") {
    const partnerIds = session
      ? session.participant_ids.filter((id) => id !== agent.id)
      : [agent.action_target_id];
    const names = partnerIds
      .map((id) => frame?.agents.find((other) => other.id === id)?.name)
      .filter(Boolean);
    if (names.length) return `Talking with ${names.join(", ")}`;
  }
  switch (agent.routine_state) {
    case "sleeping":
      return "Sleeping";
    case "returning_home":
      return "Heading home";
    case "seeking_shelter":
      return "Seeking shelter";
    case "resting":
      return "Resting";
    case "talking":
      return agent.activity_until_calendar_seconds == null
        ? "Talking"
        : `Talking until ${clockTime(agent.activity_until_calendar_seconds)}`;
    default:
      return agent.action.replaceAll("_", " ");
  }
}
