import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Mic, User } from "lucide-react";
import { db } from "@/lib/data/db";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ActionForm } from "@/components/ui/action-form";
import { FadeIn } from "@/components/ratified-ui";
import { updateRecordingMeta } from "@/app/actions";

const INPUT_CLS =
  "w-full h-9 rounded-md border border-(--color-input) bg-(--color-background) px-2 text-sm";

const STATUS_TONE: Record<string, "secondary" | "info" | "success" | "danger"> = {
  uploaded: "secondary",
  transcribing: "info",
  done: "success",
  error: "danger",
};

function fmt(d: Date): string {
  return d.toISOString().slice(0, 16).replace("T", " ");
}

export default async function RecordingDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const rec = await db.recording.findUnique({
    where: { id },
    include: { client: { select: { id: true, displayId: true, name: true } } },
  });
  if (!rec) notFound();

  return (
    <div className="space-y-5">
      <Link
        href={`/clients/${rec.clientId}`}
        className="inline-flex items-center gap-1 text-sm text-emerald-300 hover:underline"
      >
        <ArrowLeft className="size-4" /> back to client
      </Link>

      <FadeIn>
      <Card className="p-6 space-y-3 bg-grid-fade">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-2xl font-semibold tracking-tight inline-flex items-center gap-2 text-white">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-emerald-500/25 bg-emerald-500/10 text-emerald-300">
              <Mic className="size-4" />
            </span>
            {rec.title || "Recording"}
          </h1>
          <Badge variant={STATUS_TONE[rec.status] ?? "secondary"}>
            {rec.status}
          </Badge>
          {rec.reviewed && <Badge variant="success">reviewed</Badge>}
        </div>
        <Link
          href={`/clients/${rec.clientId}`}
          className="text-sm text-emerald-300 hover:underline inline-flex items-center gap-1"
        >
          <User className="size-3.5" />
          {rec.client.name} ({rec.client.displayId})
        </Link>
        <div className="text-xs text-slate-500">
          recorded {fmt(rec.createdAt)}
          {rec.durationSec ? ` · ${Math.round(rec.durationSec / 60)} min` : ""}
        </div>
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <audio controls src={`/api/recordings/${rec.id}/audio`} className="w-full" />
      </Card>
      </FadeIn>

      <FadeIn>
      <Card className="p-5">
        <h2 className="font-semibold mb-3 text-white">Details</h2>
        <ActionForm action={updateRecordingMeta}>
          <input type="hidden" name="id" value={rec.id} />
          <div className="space-y-3 text-sm">
            <label className="block">
              <span className="text-[10px] uppercase tracking-wider font-semibold text-slate-500 block mb-1">
                Title
              </span>
              <input
                name="title"
                defaultValue={rec.title ?? ""}
                placeholder="e.g. Listing consult, Buyer call"
                className={INPUT_CLS}
              />
            </label>
            <label className="inline-flex items-center gap-2">
              <input
                type="checkbox"
                name="reviewed"
                defaultChecked={rec.reviewed}
                className="size-4"
              />
              <span className="text-sm">Reviewed — extracted detail checked</span>
            </label>
            <div>
              <Button type="submit">Save</Button>
            </div>
          </div>
        </ActionForm>
      </Card>
      </FadeIn>

      <FadeIn>
      <Card className="p-5">
        <h2 className="font-semibold mb-3 text-white">Transcript</h2>
        {rec.transcript ? (
          <div className="text-sm whitespace-pre-wrap max-h-[420px] overflow-y-auto leading-relaxed text-slate-300">
            {rec.transcript}
          </div>
        ) : (
          <p className="text-sm text-slate-500 italic">
            {rec.status === "error"
              ? `Transcription failed: ${rec.error ?? "unknown error"}`
              : "No transcript yet."}
          </p>
        )}
      </Card>
      </FadeIn>
    </div>
  );
}
