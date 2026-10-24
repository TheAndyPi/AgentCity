import { expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import {
  groupConversations,
  Conversations,
  Personality,
} from "../src/components/LifePanels";
import type { Dialogue } from "../src/api/types";
import { fixtureWorld } from "../src/api/fixtures";
import { defaultProfile } from "../src/api/defaults";

const line = (
  id: string,
  speaker: string,
  recipient: string,
  interaction = "exchange",
): Dialogue => ({
  id,
  interaction_id: interaction,
  tick: 2,
  speaker_id: speaker,
  recipient_ids: [recipient],
  audible_to_ids: [speaker, recipient, "citizen-3"],
  text: `Message ${id}`,
  emotion: "calm",
  intent: "talk",
  end_conversation: false,
});
it("keeps replies in sequence and separates conversations without adding overhearers as participants", () => {
  const messages = [
    line("dialogue_10", "citizen-2", "citizen-1"),
    line("dialogue_2", "citizen-1", "citizen-2"),
    line("dialogue_11", "citizen-3", "citizen-4", "other"),
  ];
  const groups = groupConversations(messages);
  expect(groups).toHaveLength(2);
  expect(groups[0].id).toBe("other");
  expect(groups[1].messages.map((message) => message.id)).toEqual([
    "dialogue_2",
    "dialogue_10",
  ]);
  expect(groups[1].participants).toEqual(["citizen-1", "citizen-2"]);
  expect(messages[0].id).toBe("dialogue_10");
});
it("renders names, recipients and actual dialogue in a transcript", () => {
  const html = renderToStaticMarkup(
    createElement(Conversations, {
      dialogue: [line("dialogue_1", "citizen-1", "citizen-2")],
      frame: fixtureWorld(),
      onAgent: () => {},
    }),
  );
  expect(html).toContain("Conversation transcript");
  expect(html).toContain("Maya Chen");
  expect(html).toContain("to Oliver Brooks");
  expect(html).toContain("Message dialogue_1");
});
it("exposes all six actual trait scores with accessible meters", () => {
  const html = renderToStaticMarkup(
    createElement(Personality, {
      profile: {
        ...defaultProfile,
        traits: { ...defaultProfile.traits, empathy: 17 },
      },
    }),
  );
  expect(html.match(/role="meter"/g)).toHaveLength(6);
  expect(html).toContain(
    'aria-label="Empathy" aria-valuemin="0" aria-valuemax="100" aria-valuenow="17"',
  );
  expect(html).toContain("Practical");
});
