"use client";

import { useRef } from "react";
import { AudioPlayer } from "@/components/clients/audio-player";
import { cn } from "@/lib/utils";

interface Paragraph {
  speaker: number;
  start: number;
  end: number;
  text: string;
}

interface Props {
  recordingId: string;
  mimeType: string;
  transcript: string;
  paragraphs: Paragraph[];
}

function speakerLabel(idx: number): string {
  return `Speaker ${idx + 1}`;
}

function timeStr(s: number): string {
  const mm = Math.floor(s / 60);
  const ss = Math.floor(s % 60);
  return `${mm}:${ss.toString().padStart(2, "0")}`;
}

/** Side-by-side audio + diarized transcript. Click any line in the
 * transcript and the audio seeks to that point. */
export function TranscriptView({
  recordingId,
  mimeType,
  transcript,
  paragraphs,
}: Props) {
  const audioRef = useRef<HTMLAudioElement>(null);

  function seekTo(seconds: number) {
    const a = audioRef.current;
    if (!a) return;
    a.currentTime = seconds;
    a.play().catch(() => {
      /* play() rejects when not yet user-interacted; ignored */
    });
  }

  const hasParagraphs = paragraphs.length > 0;

  return (
    <div className="space-y-3">
      <AudioPlayer ref={audioRef} recordingId={recordingId} mimeType={mimeType} />

      {hasParagraphs ? (
        <ol className="space-y-2 text-sm max-h-96 overflow-y-auto">
          {paragraphs.map((p, i) => {
            const isOdd = p.speaker % 2 === 1;
            return (
              <li key={i}>
                <button
                  type="button"
                  onClick={() => seekTo(p.start)}
                  className={cn(
                    "w-full text-left rounded-md p-2 transition-colors",
                    "hover:bg-(--color-accent)",
                    isOdd ? "bg-(--color-secondary)/30" : "",
                  )}
                  title={`Seek to ${timeStr(p.start)}`}
                >
                  <span className="flex items-baseline gap-2">
                    <span
                      className={cn(
                        "text-[10px] uppercase tracking-wider font-semibold shrink-0",
                        isOdd
                          ? "text-(--color-info)"
                          : "text-(--color-success)",
                      )}
                    >
                      {speakerLabel(p.speaker)}
                    </span>
                    <span className="font-mono tabular-nums text-[10px] text-(--color-muted-foreground) shrink-0">
                      {timeStr(p.start)}
                    </span>
                  </span>
                  <p className="text-sm mt-0.5 whitespace-pre-wrap">{p.text}</p>
                </button>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="text-sm whitespace-pre-wrap leading-relaxed max-h-96 overflow-y-auto p-2">
          {transcript}
        </p>
      )}
    </div>
  );
}
