import { useState } from "react";
import { Volume2 } from "lucide-react";
import { useApp, messageOf } from "../state/app";
import { Button, ErrorBox } from "./ui";
export default function Narration({
  simulationId,
  sourceType,
  sourceId,
}: {
  simulationId: string;
  sourceType: "event" | "decision" | "dialogue";
  sourceId: string;
}) {
  const { client, capabilities } = useApp();
  const [audio, setAudio] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  if (!capabilities?.narration) return null;
  return (
    <div className="narration">
      {audio ? (
        <audio controls src={audio} aria-label="Recorded text narration" />
      ) : (
        <Button
          kind="secondary"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            void client
              .narration(simulationId, sourceType, sourceId)
              .then((r) => setAudio(r.audio_url))
              .catch((e) => setError(messageOf(e)))
              .finally(() => setBusy(false));
          }}
        >
          <Volume2 size={14} />
          {busy ? "Preparing narration…" : "Listen to this record"}
        </Button>
      )}
      {error && <ErrorBox error={error} />}
    </div>
  );
}
