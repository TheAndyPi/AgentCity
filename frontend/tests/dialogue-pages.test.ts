import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AgentCityClient } from "../src/api/client";
import { fixtureWorld } from "../src/api/fixtures";
import { Conversations } from "../src/components/LifePanels";
import { useDialoguePages } from "../src/state/dialogue";
import type { Dialogue } from "../src/api/types";

const line = (i: number): Dialogue => ({
  id: `line_${i}`,
  interaction_id: `chat_${i}`,
  tick: i,
  speaker_id: "citizen-1",
  recipient_ids: ["citizen-2"],
  audible_to_ids: [],
  text: `Live message ${i}`,
  intent: "chat",
  emotion: "calm",
  end_conversation: false,
});

describe("bounded conversation loading", () => {
  it("sends one filtered page request instead of exhausting history", async () => {
    const paths: string[] = [];
    const client = new AgentCityClient({
      mode: "live",
      request: async (_method, path) => {
        paths.push(path);
        return {
          schema_version: "1.0.0",
          request_id: crypto.randomUUID(),
          data: { items: [line(1)], next_cursor: "older" },
        };
      },
    });
    const result = await client.dialoguePage("a city", {
      cursor: "pinned cursor",
      agentId: "citizen-1",
      interactionId: "chat_1",
      limit: 50,
    });
    expect(result.next_cursor).toBe("older");
    expect(paths).toHaveLength(1);
    const url = new URL(paths[0], "https://fixture.local");
    expect(url.pathname).toBe("/simulations/a%20city/dialogue");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      cursor: "pinned cursor",
      agent_id: "citizen-1",
      interaction_id: "chat_1",
      limit: "50",
    });
  });

  it("renders recent dialogue before a background page request can finish", () => {
    let requests = 0;
    const client = new AgentCityClient({
      mode: "live",
      request: async () => {
        requests++;
        return new Promise(() => {});
      },
    });
    function Immediate() {
      const pages = useDialoguePages(client, "city", undefined, [line(1)]);
      return createElement(
        "p",
        null,
        pages.messages.map((message) => message.text).join(" "),
      );
    }
    expect(renderToStaticMarkup(createElement(Immediate))).toContain(
      "Live message 1",
    );
    expect(requests).toBe(0);
  });

  it("initially renders a bounded set of conversation cards", () => {
    const html = renderToStaticMarkup(
      createElement(Conversations, {
        dialogue: Array.from({ length: 150 }, (_, i) => line(i)),
        frame: fixtureWorld(),
        onAgent: () => {},
      }),
    );
    expect((html.match(/aria-pressed=/g) ?? []).length).toBe(30);
    expect(html).toContain("Show more conversations");
    expect(html).toContain("Live message 149");
  });
});
