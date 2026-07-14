"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { Mic, Pause, Play, Square, Upload } from "lucide-react";
import { toast } from "sonner";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { ConsentModal } from "@/components/clients/consent-modal";
import { cn } from "@/lib/utils";

type State = "idle" | "recording" | "paused" | "uploading";

interface Props {
  clientId: string;
}

/** Browser MediaRecorder UI. Click Record → permission prompt → live timer +
 * waveform amplitude bar → Stop uploads the blob to /api/recordings and
 * background transcription kicks off. */
export function RecordButton({ clientId }: Props) {
  const [state, setState] = useState<State>("idle");
  const [consentOpen, setConsentOpen] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [amplitude, setAmplitude] = useState(0);
  const [isPending, startTransition] = useTransition();
  const router = useRouter();

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafRef = useRef<number | null>(null);
  const startedAtRef = useRef<number>(0);
  const pausedAccumRef = useRef<number>(0);
  const pauseStartRef = useRef<number>(0);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  /** Tear down all audio resources on unmount or stop. */
  function cleanup() {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    if (timerRef.current) clearInterval(timerRef.current);
    streamRef.current?.getTracks().forEach((t) => t.stop());
    audioCtxRef.current?.close().catch(() => {});
    streamRef.current = null;
    audioCtxRef.current = null;
    analyserRef.current = null;
    rafRef.current = null;
    timerRef.current = null;
    setAmplitude(0);
  }

  useEffect(() => cleanup, []);

  async function startRecording() {
    setConsentOpen(false);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      streamRef.current = stream;

      // Live amplitude meter
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = new AudioCtx();
      audioCtxRef.current = ctx;
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      src.connect(analyser);
      analyserRef.current = analyser;
      const buf = new Uint8Array(analyser.frequencyBinCount);
      function tick() {
        analyser.getByteTimeDomainData(buf);
        let peak = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = Math.abs(buf[i] - 128);
          if (v > peak) peak = v;
        }
        setAmplitude(peak / 128);
        rafRef.current = requestAnimationFrame(tick);
      }
      tick();

      const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      const rec = new MediaRecorder(stream, { mimeType: mime });
      chunksRef.current = [];
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      rec.onstop = async () => {
        setState("uploading");
        const blob = new Blob(chunksRef.current, { type: mime });
        const fd = new FormData();
        fd.append("audio", blob, `call-${Date.now()}.webm`);
        fd.append("clientId", clientId);
        try {
          const res = await fetch("/api/recordings", {
            method: "POST",
            body: fd,
          });
          const data = await res.json();
          if (res.ok) {
            toast.success(
              data.transcriptionEnabled
                ? "Recording uploaded — transcribing in background"
                : "Recording saved (transcription disabled — add DEEPGRAM_API_KEY to .env.local)",
            );
            router.refresh();
          } else {
            toast.error(data.error ?? "Upload failed");
          }
        } catch (e) {
          toast.error((e as Error).message);
        } finally {
          cleanup();
          setState("idle");
          setElapsedMs(0);
          pausedAccumRef.current = 0;
        }
      };
      recorderRef.current = rec;
      rec.start(1000);

      startedAtRef.current = Date.now();
      pausedAccumRef.current = 0;
      timerRef.current = setInterval(() => {
        if (recorderRef.current?.state === "paused") return;
        setElapsedMs(Date.now() - startedAtRef.current - pausedAccumRef.current);
      }, 100);
      setState("recording");
    } catch (e) {
      const message = (e as Error).message;
      if (message.includes("Permission") || message.includes("NotAllowed")) {
        toast.error("Microphone permission denied. Enable it in browser settings.");
      } else {
        toast.error(`Could not start recording: ${message}`);
      }
      cleanup();
      setState("idle");
    }
  }

  function attemptRecord() {
    // Show consent modal (which auto-confirms if already acknowledged)
    setConsentOpen(true);
  }

  function pauseResume() {
    const rec = recorderRef.current;
    if (!rec) return;
    if (rec.state === "recording") {
      pauseStartRef.current = Date.now();
      rec.pause();
      setState("paused");
    } else if (rec.state === "paused") {
      pausedAccumRef.current += Date.now() - pauseStartRef.current;
      rec.resume();
      setState("recording");
    }
  }

  function stopRecording() {
    recorderRef.current?.stop();
  }

  async function handleFileUpload(file: File) {
    setState("uploading");
    const fd = new FormData();
    fd.append("audio", file, file.name);
    fd.append("clientId", clientId);
    fd.append("filename", file.name);
    startTransition(async () => {
      try {
        const res = await fetch("/api/recordings", { method: "POST", body: fd });
        const data = await res.json();
        if (res.ok) {
          toast.success(
            data.transcriptionEnabled
              ? `${file.name} uploaded — transcribing in background`
              : `${file.name} saved (transcription disabled)`,
          );
          router.refresh();
        } else {
          toast.error(data.error ?? "Upload failed");
        }
      } catch (e) {
        toast.error((e as Error).message);
      } finally {
        setState("idle");
      }
    });
  }

  const mm = Math.floor(elapsedMs / 60000);
  const ss = Math.floor((elapsedMs / 1000) % 60);
  const timeStr = `${mm}:${ss.toString().padStart(2, "0")}`;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <ConsentModal
        open={consentOpen}
        onAcknowledged={() => {
          setConsentOpen(false);
          startRecording();
        }}
        onCancel={() => setConsentOpen(false)}
      />

      {state === "idle" && (
        <>
          <Button onClick={attemptRecord} disabled={isPending}>
            <Mic className="size-4" /> Record
          </Button>
          <label className="inline-flex items-center gap-1.5 cursor-pointer text-sm text-(--color-muted-foreground) hover:text-(--color-foreground)">
            <Upload className="size-3.5" />
            <span>Upload voice memo</span>
            <input
              type="file"
              accept="audio/*"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleFileUpload(f);
                e.currentTarget.value = "";
              }}
            />
          </label>
        </>
      )}

      {(state === "recording" || state === "paused") && (
        <>
          <span
            className={cn(
              "size-3 rounded-full",
              state === "recording"
                ? "bg-(--color-destructive) animate-pulse"
                : "bg-(--color-muted-foreground)",
            )}
          />
          <span className="font-mono tabular-nums text-sm">{timeStr}</span>
          {/* Amplitude bar */}
          <div className="h-2 w-24 rounded-full bg-(--color-muted) overflow-hidden">
            <div
              className="h-full bg-(--color-success) transition-all"
              style={{ width: `${Math.min(100, amplitude * 200)}%` }}
            />
          </div>
          <Button variant="outline" size="sm" onClick={pauseResume}>
            {state === "recording" ? (
              <>
                <Pause className="size-3.5" /> Pause
              </>
            ) : (
              <>
                <Play className="size-3.5" /> Resume
              </>
            )}
          </Button>
          <Button variant="destructive" size="sm" onClick={stopRecording}>
            <Square className="size-3.5" /> Stop
          </Button>
        </>
      )}

      {state === "uploading" && (
        <span className="text-sm text-(--color-muted-foreground) inline-flex items-center gap-2">
          <span className="size-3 rounded-full bg-(--color-info) animate-pulse" />
          Uploading…
        </span>
      )}
    </div>
  );
}
