"use client";

import { forwardRef } from "react";

interface Props {
  recordingId: string;
  mimeType?: string;
}

/** Authenticated audio playback. Streams from /api/recordings/[id]/audio so
 * the raw file never lives in the public URL space. Forwards ref so a
 * parent (TranscriptView) can call `currentTime = …` to seek. */
export const AudioPlayer = forwardRef<HTMLAudioElement, Props>(
  function AudioPlayer({ recordingId, mimeType }, ref) {
    return (
      <audio
        ref={ref}
        controls
        preload="metadata"
        className="w-full"
        src={`/api/recordings/${recordingId}/audio`}
        // mime hint helps Safari
        {...(mimeType ? { type: mimeType } : {})}
      />
    );
  },
);
