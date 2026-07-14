/** Deepgram Nova-3 transcription wrapper.
 *
 * Returns the full transcript plus speaker-diarized paragraphs with
 * timestamps. Throws when DEEPGRAM_API_KEY isn't configured so the caller
 * can degrade gracefully — the recording pipeline still completes the
 * upload step without it.
 */

import { createReadStream } from "node:fs";
import { DeepgramClient } from "@deepgram/sdk";

export interface TranscriptParagraph {
  speaker: number;
  start: number; // seconds
  end: number;
  text: string;
}

export interface TranscribeResult {
  text: string;
  paragraphs: TranscriptParagraph[];
  durationSec: number;
}

export function isTranscriptionConfigured(): boolean {
  return Boolean(process.env.DEEPGRAM_API_KEY);
}

// Loose shape of the bits of the Deepgram response we touch — the SDK
// types are complex so we just describe what we actually read.
interface DeepgramParagraph {
  speaker?: number;
  start?: number;
  end?: number;
  sentences?: Array<{ text: string }>;
}

interface DeepgramAlternative {
  transcript?: string;
  paragraphs?: { paragraphs?: DeepgramParagraph[] };
}

interface DeepgramResponse {
  metadata?: { duration?: number };
  results?: {
    channels?: Array<{
      alternatives?: DeepgramAlternative[];
    }>;
  };
}

export async function transcribe(filePath: string, mimeType: string): Promise<TranscribeResult> {
  const apiKey = process.env.DEEPGRAM_API_KEY;
  if (!apiKey) {
    throw new Error(
      "DEEPGRAM_API_KEY is not set. Add it to .env.local — recordings will save but transcription is disabled until then.",
    );
  }

  const client = new DeepgramClient({ apiKey });
  const stream = createReadStream(filePath);

  const response = (await client.listen.v1.media.transcribeFile(stream, {
    model: "nova-3",
    smart_format: true,
    punctuate: true,
    diarize: true,
    paragraphs: true,
    language: "en-US",
    mimetype: mimeType,
  })) as DeepgramResponse;

  const alt = response.results?.channels?.[0]?.alternatives?.[0];
  if (!alt) {
    throw new Error("Deepgram returned no transcript alternatives");
  }

  const text = alt.transcript ?? "";
  const durationSec = response.metadata?.duration ?? 0;

  const rawParagraphs = alt.paragraphs?.paragraphs ?? [];
  const paragraphs: TranscriptParagraph[] = rawParagraphs.map((p) => ({
    speaker: p.speaker ?? 0,
    start: p.start ?? 0,
    end: p.end ?? 0,
    text: (p.sentences ?? []).map((s) => s.text).join(" ").trim(),
  }));

  return { text, paragraphs, durationSec: Math.round(durationSec) };
}
