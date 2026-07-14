import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, DoorOpen, MapPin } from "lucide-react";
import { db } from "@/lib/data/db";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ActionForm } from "@/components/ui/action-form";
import { updateDoorknock } from "@/app/actions";

const KNOCK_OUTCOMES = [
  "interested", "talk_later", "left_flyer", "nobody_home", "not_interested",
];

const INPUT_CLS =
  "w-full h-9 rounded-md border border-(--color-input) bg-(--color-background) px-2 text-sm";

function fmt(d: Date): string {
  return d.toISOString().slice(0, 16).replace("T", " ");
}

export default async function DoorknockDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const knock = await db.doorknock.findUnique({ where: { id: Number(id) } });
  if (!knock) notFound();

  return (
    <div className="space-y-5">
      <Link
        href="/activity"
        className="inline-flex items-center gap-1 text-sm text-(--color-info) hover:underline"
      >
        <ArrowLeft className="size-4" /> back
      </Link>

      <Card className="p-6 space-y-3">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-2xl font-bold inline-flex items-center gap-2">
            <DoorOpen className="size-5" /> Door-knock
          </h1>
          <Badge variant="secondary" className="capitalize">
            {knock.outcome.replace(/_/g, " ")}
          </Badge>
        </div>
        <div className="text-sm">
          <div className="font-semibold">{knock.owner || "—"}</div>
          <Link
            href={`/property/${encodeURIComponent(knock.parcelId)}?county=${knock.county}`}
            className="text-(--color-info) hover:underline inline-flex items-center gap-1"
            target="_blank"
            rel="noreferrer"
          >
            <MapPin className="size-3.5" /> {knock.siteAddr || knock.parcelId}
          </Link>
          <div className="text-xs text-(--color-muted-foreground) mt-1">
            {knock.county} · logged {fmt(knock.timestamp)}
          </div>
        </div>
      </Card>

      <Card className="p-5">
        <h2 className="font-semibold mb-3">Edit door-knock</h2>
        <ActionForm action={updateDoorknock}>
          <input type="hidden" name="id" value={knock.id} />
          <div className="space-y-3 text-sm">
            <label className="block">
              <span className="text-[10px] uppercase tracking-wider font-semibold text-(--color-muted-foreground) block mb-1">
                Outcome
              </span>
              <select name="outcome" defaultValue={knock.outcome} className={INPUT_CLS}>
                {KNOCK_OUTCOMES.map((o) => (
                  <option key={o} value={o} className="capitalize">
                    {o.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-[10px] uppercase tracking-wider font-semibold text-(--color-muted-foreground) block mb-1">
                Notes
              </span>
              <textarea
                name="notes"
                rows={4}
                defaultValue={knock.notes ?? ""}
                className={`${INPUT_CLS} h-auto py-2`}
              />
            </label>
            <Button type="submit">Save</Button>
          </div>
        </ActionForm>
      </Card>
    </div>
  );
}
