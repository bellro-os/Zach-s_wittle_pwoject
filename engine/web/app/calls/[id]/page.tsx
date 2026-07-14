import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Phone, MapPin } from "lucide-react";
import { db } from "@/lib/data/db";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ActionForm } from "@/components/ui/action-form";
import { FadeIn } from "@/components/ratified-ui";
import { updateCall } from "@/app/actions";

const CALL_OUTCOMES = [
  "interested", "callback", "meeting_scheduled", "talk_later",
  "left_voicemail", "no_answer", "not_interested", "bad_number",
  "dnc", "wrong_owner",
];

const INPUT_CLS =
  "w-full h-9 rounded-md border border-(--color-input) bg-(--color-background) px-2 text-sm";

function fmt(d: Date): string {
  return d.toISOString().slice(0, 16).replace("T", " ");
}

export default async function CallDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const call = await db.call.findUnique({ where: { id: Number(id) } });
  if (!call) notFound();

  return (
    <div className="space-y-5">
      <Link
        href="/activity"
        className="inline-flex items-center gap-1 text-sm text-emerald-300 hover:underline"
      >
        <ArrowLeft className="size-4" /> back
      </Link>

      <FadeIn>
      <Card className="p-6 space-y-3 bg-grid-fade">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-2xl font-semibold tracking-tight inline-flex items-center gap-2 text-white">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-emerald-500/25 bg-emerald-500/10 text-emerald-300">
              <Phone className="size-4" />
            </span>
            Call
          </h1>
          <Badge variant="secondary" className="capitalize">
            {call.outcome.replace(/_/g, " ")}
          </Badge>
        </div>
        <div className="text-sm">
          <div className="font-semibold text-white">{call.owner || "—"}</div>
          <Link
            href={`/property/${encodeURIComponent(call.parcelId)}?county=${call.county}`}
            className="text-emerald-300 hover:underline inline-flex items-center gap-1"
            target="_blank"
            rel="noreferrer"
          >
            <MapPin className="size-3.5" /> {call.siteAddr || call.parcelId}
          </Link>
          <div className="text-xs text-slate-500 mt-1">
            {call.county} · logged {fmt(call.timestamp)}
            {call.nextFollowup
              ? ` · follow-up ${call.nextFollowup.toISOString().slice(0, 10)}`
              : ""}
          </div>
        </div>
      </Card>
      </FadeIn>

      <FadeIn>
      <Card className="p-5">
        <h2 className="font-semibold mb-3 text-white">Edit call</h2>
        <ActionForm action={updateCall}>
          <input type="hidden" name="id" value={call.id} />
          <div className="space-y-3 text-sm">
            <label className="block">
              <span className="text-[10px] uppercase tracking-wider font-semibold text-slate-500 block mb-1">
                Outcome
              </span>
              <select name="outcome" defaultValue={call.outcome} className={INPUT_CLS}>
                {CALL_OUTCOMES.map((o) => (
                  <option key={o} value={o} className="capitalize">
                    {o.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-[10px] uppercase tracking-wider font-semibold text-slate-500 block mb-1">
                Notes
              </span>
              <textarea
                name="notes"
                rows={4}
                defaultValue={call.notes ?? ""}
                className={`${INPUT_CLS} h-auto py-2`}
              />
            </label>
            <Button type="submit">Save</Button>
          </div>
        </ActionForm>
        <p className="text-[10px] text-slate-500 mt-3">
          Changing the outcome re-derives the follow-up date and queue
          suppression.
        </p>
      </Card>
      </FadeIn>
    </div>
  );
}
