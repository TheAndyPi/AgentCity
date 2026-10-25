import {
  AudioLines,
  Pause,
  Play,
  SlidersHorizontal,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useId,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import type { WorldFrame } from "../api/types";
import type { WorldStore } from "../state/world";
import { useApp } from "../state/app";
import { LiveVoices, type ListeningScope } from "./live";
import "./narration.css";
import { Soundscape } from "./soundscape";
import type { DisasterState } from "../disasters/client";

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
  disasters,
  listeningPoint,
}: {
  children: ReactNode;
  scope: ListeningScope;
  frame: WorldFrame;
  store: WorldStore;
  disasters?: DisasterState | null;
  listeningPoint?: { x: number; y: number };
}) {
  const { client, capabilities } = useApp();
  const voices = useMemo(
    () => new LiveVoices(client, new Audio(), preferences()),
    [client, store],
  );
  const sounds = useMemo(
    () => new Soundscape(client, voices),
    [client, voices],
  );
  const sound = useSyncExternalStore(sounds.subscribe, sounds.getSnapshot);
  const view = useSyncExternalStore(voices.subscribe, voices.getSnapshot);
  const [expanded, setExpanded] = useState(false);
  const panelId = useId();
  const available =
    capabilities?.narration ||
    Object.values(sound.categories).some((v) => v !== "unconfigured");
  const dock = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const node = dock.current;
    const stage = node?.previousElementSibling;
    if (!node || !(stage instanceof HTMLElement)) return;
    const sync = () =>
      stage.style.setProperty(
        "--audio-dock-height",
        `${node.getBoundingClientRect().height + 12}px`,
      );
    sync();
    const observer = new ResizeObserver(sync);
    observer.observe(node);
    return () => {
      observer.disconnect();
      stage.style.removeProperty("--audio-dock-height");
    };
  }, [available, expanded, sounds]);
  const currentAudio = useRef({ view, sound });
  currentAudio.current = { view, sound };
  const scopeKey = JSON.stringify(scope);
  useEffect(() => {
    void sounds.capabilities();
    return () => sounds.dispose();
  }, [sounds]);
  useLayoutEffect(() => {
    sounds.update(disasters ?? null, frame, scope, view, listeningPoint);
  }, [sounds, disasters, frame, scopeKey, view, listeningPoint]);
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
      sounds.stop();
      voices.visibility(document.hidden);
      if (document.hidden)
        document.querySelectorAll("audio").forEach((audio) => audio.pause());
    };
    const revoked = () => {
      sounds.stop();
      voices.revoke();
      document.querySelectorAll("audio").forEach((audio) => audio.pause());
    };
    const exclusive = (event: Event) => {
      const target = event.target;
      if (!(target instanceof HTMLAudioElement)) return;
      if (target.dataset.audioBus) return;
      target.volume = currentAudio.current.view.volume;
      target.muted =
        currentAudio.current.view.muted || !currentAudio.current.sound.voices;
      if (target.muted) target.pause();
      document.querySelectorAll("audio").forEach((audio) => {
        if (audio !== target && !audio.dataset.audioBus) audio.pause();
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
      {available && (
        <section
          ref={dock}
          className={`live-voices${expanded ? " is-expanded" : " is-collapsed"}`}
          aria-label="Live voices"
          data-sound-enabled={sound.enabled}
          data-sound-events={
            disasters?.events.filter((e) => e.phase === "active").length ?? 0
          }
        >
          <button
            className="audio-dock-toggle"
            aria-label={expanded ? "Hide city radio" : "Show city radio"}
            aria-expanded={expanded}
            aria-controls={panelId}
            onClick={() => setExpanded((open) => !open)}
          >
            {expanded ? <X size={16} /> : <AudioLines size={16} />}
            <span>{expanded ? "Hide radio" : "City radio"}</span>
            {!expanded && (
              <span
                className="audio-status-dot"
                data-active={view.enabled && !view.paused && !view.muted}
              />
            )}
          </button>
          <div id={panelId} hidden={!expanded}>
            <div className="live-voice-controls">
              <div className="audio-identity">
                <span className="audio-emblem">
                  <AudioLines size={20} />
                </span>
                <div>
                  <strong>City radio</strong>
                  <span>
                    {view.speaking
                      ? `On air · ${speaker}`
                      : view.enabled && !view.paused && !view.muted
                        ? "Listening to the city"
                        : "Your city, in sound"}
                  </span>
                </div>
              </div>
              <button
                className="audio-play"
                aria-label={
                  !view.enabled
                    ? "Enable live voices"
                    : view.paused
                      ? "Resume listening"
                      : "Pause audio"
                }
                disabled={view.hidden}
                onClick={() => {
                  if (!view.enabled || view.paused) {
                    sounds.enable();
                    voices.enable();
                  } else {
                    sounds.stop();
                    voices.pause();
                  }
                }}
              >
                {!view.enabled || view.paused ? (
                  <Play size={18} fill="currentColor" />
                ) : (
                  <Pause size={18} fill="currentColor" />
                )}
              </button>
              <button
                className="audio-mute"
                aria-label={view.muted ? "Unmute voices" : "Mute voices"}
                aria-pressed={view.muted}
                onClick={() => {
                  sounds.stop();
                  document.querySelectorAll("audio").forEach((a) => {
                    a.pause();
                    a.muted = !view.muted;
                  });
                  voices.mute(!view.muted);
                }}
              >
                {view.muted ? <VolumeX size={18} /> : <Volume2 size={18} />}
              </button>
              <label className="audio-volume">
                <span className="audio-sr-only">Master volume</span>
                <input
                  aria-label="Voice volume"
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={view.volume}
                  onChange={(e) => {
                    const value = Number(e.target.value);
                    document.querySelectorAll("audio").forEach((a) => {
                      a.volume = value;
                    });
                    voices.setVolume(value);
                  }}
                />
                <output>{Math.round(view.volume * 100)}%</output>
              </label>
              <details className="sound-mix">
                <summary>
                  <SlidersHorizontal size={16} />
                  <span>Sound mix</span>
                </summary>
                <div className="sound-mix-options">
                  {(["effects", "music", "voices"] as const).map((category) => (
                    <label key={category}>
                      <input
                        type="checkbox"
                        checked={sound[category]}
                        onChange={() => {
                          sounds.toggle(category);
                          if (category === "voices")
                            document.querySelectorAll("audio").forEach((a) => {
                              a.pause();
                              a.muted = sound.voices;
                            });
                        }}
                      />
                      {category}
                    </label>
                  ))}
                  <small>
                    Effects: {sound.categories.effects} · Music:{" "}
                    {sound.categories.music} · Reactions:{" "}
                    {sound.categories.reactions}
                  </small>
                  {sound.error && <span role="status">{sound.error}</span>}
                </div>
              </details>
              {scope.subject?.kind === "interaction" && (
                <button disabled={view.hidden} onClick={() => voices.replay()}>
                  Replay this conversation
                </button>
              )}
              {(view.queued > 1 || view.blocked || view.missed) && (
                <button onClick={() => voices.catchUp()}>Catch up live</button>
              )}
            </div>
            <span className="audio-status" role="status">
              <span
                className="audio-status-dot"
                data-active={view.enabled && !view.paused && !view.muted}
              />
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
          </div>
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
