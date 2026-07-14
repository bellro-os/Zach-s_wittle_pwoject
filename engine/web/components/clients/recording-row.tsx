"use client";

import Link from "next/link";
import { useEffect, useState, useTransition } from "react";
import { toast } from "sonner";
import { useRouter } from "next/navigation";
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  AlertTriangle,
  Trash2,
  RotateCcw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  AlertDialog,
  AlertDialogTrigger,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogAction,
  AlertDialogCancel,
} from "@/components/ui/alert-dialog";
import { TranscriptView } from "@/components/clients/transcript-view";
import { cn } from "@/lib/utils";

interface Recording {
  id: string;
  status: string;
  durationSec: number | null;
  sizeBytes: number | null;
  mimeType: string;
  transcript: string | null;
  segmentsJson: string | null;
  createdAt: Date;
  completedAt: Date | null;
  error: string | null;
}

function formatDuration(s: number | null): string {
  if (s == null) return "—";
  const mm = Math.floor(s / 60);
  const ss = s % 60;
  return `${mm}:${ss.toString().padStart(2, "0")}`;
}

function formatSize(bytes: number | null): string {
  if (!bytes) return "";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const STATUS_TONE: Record<
  string,
  { variant: "secondary" | "info" | "success" | "danger" | "warning"; label: string }
> = {
  uploaded: { variant: "secondary", label: "Uploaded" },
  transcribing: { variant: "info", label: "Transcribing" },
  done: { variant: "success", label: "Done" },
  error: { variant: "danger", label: "Error" },
};

/** Single recording row. Polls the API for status updates while transcribing. */
export function RecordingRow({ recording }: { recording: Recording }) {
  const router = useRouter();
  const [rec, setRec] = useState<Recording>(recording);
  const [expanded, setExpanded] = useState(false);
  const [isPending, startTransition] = useTransition();

  // Poll while transcribing (every 4s, max 5 min)
  useEffect(() => {
    if (rec.status !== "transcribing" && rec.status !== "uploaded") return;
    let attempts = 0;
    const interval = setInterval(async () => {
      attempts++;
      if (attempts > 75) {
        clearInterval(interval);
        return;
      }
      try {
        const res = await fetch(`/api/recordings/${rec.id}`);
        if (res.ok) {
          const data = (await res.json()) as Recording;
          setRec({
            ...data,
            createdAt: new Date(data.createdAt),
            completedAt: data.completedAt ? new Date(data.completedAt) : null,
          });
          if (data.status === "done" || data.status === "error") {
            clearInterval(interval);
            router.refresh();
          }
        }
      } catch {
        // Network blip; keep trying
      }
    }, 4000);
    return () => clearInterval(interval);
  }, [rec.id, rec.status, router]);

  const tone = STATUS_TONE[rec.status] ?? STATUS_TONE.uploaded;
  const hasTranscript = rec.status === "done" && rec.transcript;
  const paragraphs = rec.segmentsJson ? JSON.parse(rec.segmentsJson) : [];

  function retry() {
    startTransition(async () => {
      try {
        const res = await fetch(`/api/recordings/${rec.id}/process`, {
          method: "POST",
        });
        const data = await res.json();
        if (res.ok) {
          toast.success("Re-transcribing");
          setRec({ ...rec, status: "transcribing", error: null });
        } else {
          toast.error(data.error ?? "Could not retry");
        }
      } catch (e) {
        toast.error((e as Error).message);
      }
    });
  }

  async function handleDelete() {
    try {
      const res = await fetch(`/api/recordings/${rec.id}`, { method: "DELETE" });
      if (res.ok) {
        toast.success("Recording deleted");
        router.refresh();
      } else {
        toast.error("Could not delete");
      }
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <li className="py-3">
      <div className="flex items-center gap-3 flex-wrap">
        <button
          type="button"
          onClick={() => hasTranscript && setExpanded(!expanded)}
          className={cn(
            "size-7 inline-flex items-center justify-center rounded-md border border-(--color-border)",
            hasTranscript
              ? "hover:bg-(--color-accent) cursor-pointer"
              : "opacity-40 cursor-default",
          )}
          aria-label={expanded ? "Collapse" : "Expand"}
        >
          {rec.status === "transcribing" || rec.status === "uploaded" ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : rec.status === "error" ? (
            <AlertTriangle className="size-3.5 text-(--color-destructive)" />
          ) : expanded ? (
            <ChevronDown className="size-3.5" />
          ) : (
            <ChevronRight className="size-3.5" />
          )}
        </button>

        <Badge variant={tone.variant} className="text-xs">
          {tone.label}
        </Badge>

        <span className="font-mono tabular-nums text-sm">
          {formatDuration(rec.durationSec)}
        </span>
        <span className="text-xs text-(--color-muted-foreground)">
          {formatSize(rec.sizeBytes)}
        </span>
        <span className="text-xs text-(--color-muted-foreground) tabular-nums">
          {new Date(rec.createdAt)
            .toISOString()
            .replace("T", " ")
            .slice(0, 16)}
        </span>

        {rec.status === "error" && (
          <>
            <span
              className="text-xs text-(--color-destructive) truncate max-w-[300px]"
              title={rec.error ?? undefined}
            >
              {rec.error}
            </span>
            <Button variant="outline" size="sm" onClick={retry} disabled={isPending}>
              <RotateCcw className="size-3.5" /> Retry
            </Button>
          </>
        )}

        <div className="ml-auto flex items-center gap-2">
          <Link
            href={`/recordings/${rec.id}`}
            className="text-[10px] text-(--color-info) hover:underline"
          >
            open ›
          </Link>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <button
                type="button"
                className="text-[10px] text-(--color-muted-foreground) hover:text-(--color-destructive) inline-flex items-center gap-1"
              >
                <Trash2 className="size-3" /> delete
              </button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Delete this recording?</AlertDialogTitle>
                <AlertDialogDescription>
                  Removes the audio file and transcript permanently.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction onClick={handleDelete}>Delete</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      {expanded && hasTranscript && (
        <div className="mt-3 ml-10 p-3 rounded-md bg-(--color-secondary)/40">
          <TranscriptView
            recordingId={rec.id}
            mimeType={rec.mimeType}
            transcript={rec.transcript ?? ""}
            paragraphs={paragraphs}
          />
        </div>
      )}
    </li>
  );
}
