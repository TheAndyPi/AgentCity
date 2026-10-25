import { useEffect, useRef, useState } from "react";
import { Volume2 } from "lucide-react";
import { useApp, messageOf } from "../state/app";
import { Button, ErrorBox } from "./ui";
import {
  pending,
  request,
  sourceKey,
  type NarrationAudio,
  type NarrationSourceType,
} from "../narration/results";
import "../narration/narration.css";

type View =
  | { key: string; status: "idle" | "loading" | "unplayable" }
  | { key: string; status: "ready"; audio: NarrationAudio }
  | { key: string; status: "failed"; error: string };

const initial = (key: string): View => ({
  key,
  status: pending(key) ? "loading" : "idle",
});

export default function Narration({
  simulationId,
  sourceType,
  sourceId,
}: {
  simulationId: string;
  sourceType: NarrationSourceType;
  sourceId: string;
}) {
  const { client, capabilities } = useApp();
  const key = sourceKey(simulationId, sourceType, sourceId);
  const [view, setView] = useState<View>(() => initial(key));
  const latest = useRef(key);
  latest.current = key;
  // A response for a source that is no longer selected is ignored.
  const current = view.key === key ? view : initial(key);
  const settle = (requested: string, promise: Promise<NarrationAudio>) =>
    promise.then(
      (audio) => {
        if (latest.current === requested)
          setView({ key: requested, status: "ready", audio });
      },
      (error) => {
        if (latest.current === requested)
          setView({
            key: requested,
            status: "failed",
            error: messageOf(error),
          });
      },
    );
  useEffect(() => {
    setView(initial(key));
    const inFlight = pending(key);
    if (inFlight) void settle(key, inFlight);
  }, [key]);
  if (!capabilities?.narration) return null;
  const listen = () => {
    const requested = key;
    setView({ key: requested, status: "loading" });
    void settle(
      requested,
      request(requested, () =>
        client.narration(simulationId, sourceType, sourceId),
      ),
    );
  };
  const loading = current.status === "loading";
  return (
    <div
      className="narration"
      data-source={`${sourceType}:${sourceId}`}
      data-status={current.status}
    >
      {current.status === "ready" ? (
        <audio
          controls
          preload="metadata"
          src={current.audio.audio_url}
          aria-label="Recorded text narration"
          onError={() =>
            setView((v) => (v.key === key ? { key, status: "unplayable" } : v))
          }
        />
      ) : current.status === "failed" ? (
        <ErrorBox error={current.error} retry={listen} />
      ) : current.status === "unplayable" ? (
        <ErrorBox
          error="This narration could not be played. It may have expired."
          retry={listen}
        />
      ) : (
        <Button kind="secondary" disabled={loading} onClick={listen}>
          <Volume2 size={14} />
          {loading ? "Preparing narration…" : "Listen to this record"}
        </Button>
      )}
      {loading && (
        <span className="narration-status" role="status">
          Generating audio from the recorded text
        </span>
      )}
    </div>
  );
}
