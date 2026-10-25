import { describe, expect, it } from "vitest";
import { fixtureWorld } from "../src/api/fixtures";
import {
  calendarTime,
  curfewActive,
  dayPhase,
  daylight,
  activityLabel,
} from "../src/world/daylight";
import { speechBySpeaker } from "../src/world/speech";
import { world } from "../src/api/schemas";

describe("calendar and daily life", () => {
  it("uses calendar time and reads legacy simulations", () => {
    const frame = fixtureWorld();
    expect(calendarTime(frame.simulation)).toBe(8 * 3600);
    delete frame.simulation.calendar_time_seconds;
    frame.simulation.sim_time_seconds = 120;
    expect(calendarTime(frame.simulation)).toBe(120);
    expect(world.safeParse(frame).success).toBe(true);
  });
  it("blends dawn and dusk and repeats at midnight", () => {
    for (const [hour, phase, light] of [
      [0, "Night", 0],
      [5, "Dawn", 0],
      [6, "Dawn", 0.5],
      [7, "Day", 1],
      [19, "Dusk", 1],
      [20, "Dusk", 0.5],
      [21, "Night", 0],
      [24, "Night", 0],
    ] as const) {
      expect(dayPhase(hour * 3600)).toBe(phase);
      expect(daylight(hour * 3600)).toBe(light);
    }
  });
  it("handles curfew windows across midnight", () => {
    const frame = fixtureWorld();
    frame.curfew!.enabled = true;
    for (const [hour, active] of [
      [21, false],
      [22, true],
      [25, true],
      [30, false],
    ] as const) {
      frame.simulation.calendar_time_seconds = hour * 3600;
      expect(curfewActive(frame)).toBe(active);
    }
  });
  it("keeps conversation bubbles through listening and labels routine activity", () => {
    const frame = fixtureWorld();
    const agent = frame.agents[0];
    frame.ref.tick = 20;
    frame.recent_dialogue = [
      {
        id: "line",
        interaction_id: "session",
        tick: 1,
        speaker_id: agent.id,
        recipient_ids: [frame.agents[1].id],
        audible_to_ids: [],
        text: "Take your time.",
        intent: "talk",
        emotion: "calm",
        end_conversation: false,
      },
    ];
    frame.conversation_sessions = [
      {
        id: "session",
        participant_ids: [agent.id, frame.agents[1].id],
        status: "accepted",
        accepted_calendar_seconds: 28800,
        minimum_end_calendar_seconds: 32400,
        next_turn_calendar_seconds: 30000,
        end_reason: null,
      },
    ];
    expect(speechBySpeaker(frame).get(agent.id)?.text).toBe("Take your time.");
    frame.conversation_sessions[0].status = "ended";
    expect(speechBySpeaker(frame).size).toBe(0);
    agent.routine_state = "sleeping";
    expect(activityLabel(agent)).toBe("Sleeping");
    agent.routine_state = "talking";
    agent.activity_until_calendar_seconds = 32400;
    expect(activityLabel(agent)).toBe("Talking until 09:00");
  });
});
