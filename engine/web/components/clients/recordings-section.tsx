import { Mic2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { RecordButton } from "@/components/clients/record-button";
import { RecordingRow } from "@/components/clients/recording-row";
import { db } from "@/lib/data/db";
import { isTranscriptionConfigured } from "@/lib/transcribe";

interface Props {
  clientId: string;
}

/** Server Component — fetches the recordings list once. Each row then
 * client-side polls if it's still transcribing. */
export async function RecordingsSection({ clientId }: Props) {
  const recordings = await db.recording.findMany({
    where: { clientId },
    orderBy: { createdAt: "desc" },
    select: {
      id: true,
      status: true,
      durationSec: true,
      sizeBytes: true,
      mimeType: true,
      transcript: true,
      segmentsJson: true,
      createdAt: true,
      completedAt: true,
      error: true,
    },
  });

  const transcriptionOk = isTranscriptionConfigured();

  return (
    <Card className="p-5 gap-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="font-semibold inline-flex items-center gap-2">
          <Mic2 className="size-4" />
          Recordings
          <span className="text-(--color-muted-foreground) font-normal text-sm">
            ({recordings.length})
          </span>
        </h2>
        <RecordButton clientId={clientId} />
      </div>

      {!transcriptionOk && (
        <p className="text-xs text-(--color-warning) bg-(--color-warning)/10 border border-(--color-warning)/30 rounded-md px-3 py-2">
          Transcription disabled —{" "}
          <code className="font-mono">DEEPGRAM_API_KEY</code> isn&apos;t set in{" "}
          <code className="font-mono">.env.local</code>. Recordings will save
          but the transcript field will stay empty until you add the key and
          retry.
        </p>
      )}

      {recordings.length === 0 ? (
        <p className="text-sm text-(--color-muted-foreground) italic">
          No recordings yet. Click <strong>Record</strong> to start a call,
          or upload a voice memo file.
        </p>
      ) : (
        <ul className="divide-y divide-(--color-border)">
          {recordings.map((r) => (
            <RecordingRow key={r.id} recording={r} />
          ))}
        </ul>
      )}
    </Card>
  );
}
