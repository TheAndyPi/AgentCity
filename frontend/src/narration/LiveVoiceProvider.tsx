import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import type { WorldFrame } from "../api/types";
import type { WorldStore } from "../state/world";
import { useApp } from "../state/app";
import { LiveVoices, type ListeningScope } from "./live";
import "./narration.css";

function preferences() {
  try {
    const saved = JSON.parse(
      localStorage.getItem("agentcity:voice-preferences") ?? "null",
    );
    return saved &&
      typeof saved.muted === "boolean" &&
      Number.isFinite(saved.volume)
      ? { muted: saved.muted, volume: Math.max(0, Math.min(1, saved.volume)) }
      : undefined;
  } catch {
    return undefined;
  }
}

export default function LiveVoiceProvider({
  children,
  scope,
  frame,
  store,
}: {
  children: ReactNode;
  scope: ListeningScope;
  frame: WorldFrame;
  store: WorldStore;
}) {
  const { client, capabilities } = useApp();
  const voices = useMemo(
    () => new LiveVoices(client, new Audio(), preferences()),
    [client, store],
  );
  const view = useSyncExternalStore(voices.subscribe, voices.getSnapshot);
  const scopeKey = JSON.stringify(scope);
  useLayoutEffect(() => {
    // Source changes stop manual narration as well as the automatic channel.
    document.querySelectorAll("audio").forEach((audio) => audio.pause());
    voices.configure(scope, frame);
  }, [voices, scopeKey]);
  useLayoutEffect(() => {
    voices.historicalFrame(frame);
  }, [voices, frame]);
  useLayoutEffect(() => {
    const off = store.subscribe(() => {
      const current = store.getSnapshot().frame;
      if (current) voices.ingest(current);
    });
    return () => {
      off();
      voices.dispose();
      document.querySelectorAll("audio").forEach((audio) => audio.pause());
    };
  }, [store, voices]);
  useEffect(() => {
    const visibility = () => {
      voices.visibility(document.hidden);
      if (document.hidden)
        document.querySelectorAll("audio").forEach((audio) => audio.pause());
    };
    const revoked = () => {
      voices.revoke();
      document.querySelectorAll("audio").forEach((audio) => audio.pause());
    };
    const exclusive = (event: Event) => {
      const target = event.target;
      if (!(target instanceof HTMLAudioElement)) return;
      document.querySelectorAll("audio").forEach((audio) => {
        if (audio !== target) audio.pause();
      });
      if (target !== voices.player) voices.pause();
    };
    document.addEventListener("visibilitychange", visibility);
    window.addEventListener("agentcity:session-expired", revoked);
    document.addEventListener("play", exclusive, true);
    if (document.hidden) visibility();
    return () => {
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("agentcity:session-expired", revoked);
      document.removeEventListener("play", exclusive, true);
    };
  }, [voices]);
  useEffect(() => {
    try {
      localStorage.setItem(
        "agentcity:voice-preferences",
        JSON.stringify({ muted: view.muted, volume: view.volume }),
      );
    } catch {
      /* private browsing */
    }
  }, [view.muted, view.volume]);
  const speaker =
    frame.agents.find((a) => a.id === view.speaking?.speaker_id)?.name ??
    view.speaking?.speaker_id;
  return (
    <>
      {children}
      {capabilities?.narration && (
        <section className="live-voices glass" aria-label="Live voices">
          <div className="live-voice-controls">
            {!view.enabled ? (
              <button onClick={() => voices.enable()}>
                Enable live voices
              </button>
            ) : (
              <>
                <button onClick={() => voices.mute(!view.muted)}>
                  {view.muted ? "Unmute voices" : "Mute voices"}
                </button>
                <button
                  disabled={view.hidden}
                  onClick={() =>
                    view.paused ? voices.enable() : voices.pause()
                  }
                >
                  {view.paused ? "Resume listening" : "Pause audio"}
                </button>
              </>
            )}
            <label>
              Volume{" "}
              <input
                aria-label="Voice volume"
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={view.volume}
                onChange={(e) => voices.setVolume(Number(e.target.value))}
              />
            </label>
            {scope.subject?.kind === "interaction" && (
              <button disabled={view.hidden} onClick={() => voices.replay()}>
                Replay this conversation
              </button>
            )}
            {(view.queued > 1 || view.blocked || view.missed) && (
              <button onClick={() => voices.catchUp()}>Catch up live</button>
            )}
          </div>
          <span role="status">
            {view.status}
            {view.queued > 0 &&
              ` · ${view.queued} lines · ~${Math.ceil(view.seconds)}s behind`}
            {view.missed && " · Missed/backlogged dialogue requires catch up"}
          </span>
          {view.speaking && (
            <p
              className="spoken-caption"
              aria-live="polite"
              data-dialogue-id={view.speaking.id}
            >
              <strong>Now speaking: {speaker}</strong>
              <small>Conversation {view.speaking.interaction_id}</small>
              <span>{view.speaking.text}</span>
            </p>
          )}
          {view.error && (
            <p role="alert">
              {view.error}{" "}
              <button onClick={() => voices.retry()}>Retry voice</button>
              <button onClick={() => voices.skip()}>Skip this line</button>
            </p>
          )}
          {view.enabled && (
            <span
              hidden
              ref={(element) => {
                if (element && voices.player.parentNode !== element)
                  element.appendChild(voices.player);
              }}
            />
          )}
        </section>
      )}
    </>
  );
}
