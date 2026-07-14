import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Activity as ActivityIcon, User } from "lucide-react";
import { db } from "@/lib/data/db";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ActionForm } from "@/components/ui/action-form";
import { updateTouch } from "@/app/actions";

const KINDS = ["call", "text", "email", "in_person", "meeting", "letter", "note"];
const DIRECTIONS = ["", "outbound", "inbound"];

const INPUT_CLS =
  "w-full h-9 rounded-md border border-(--color-input) bg-(--color-background) px-2 text-sm";

function fmt(d: Date): string {
  return d.toISOString().slice(0, 16).replace("T", " ");
}

export default async function TouchDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const touch = await db.touch.findUnique({
    where: { id },
    include: { client: { select: { id: true, displayId: true, name: true } } },
  });
  if (!touch) notFound();

  return (
    <div className="space-y-5">
      <Link
        href={`/clients/${touch.clientId}`}
        className="inline-flex items-center gap-1 text-sm text-(--color-info) hover:underline"
      >
        <ArrowLeft className="size-4" /> back to client
      </Link>

      <Card className="p-6 space-y-3">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-2xl font-bold inline-flex items-center gap-2">
            <ActivityIcon className="size-5" /> Touch
          </h1>
          <Badge variant="secondary" className="capitalize">
            {touch.kind.replace(/_/g, " ")}
          </Badge>
          {touch.direction && (
            <Badge variant="info" className="capitalize">{touch.direction}</Badge>
          )}
        </div>
        <Link
          href={`/clients/${touch.clientId}`}
          className="text-sm text-(--color-info) hover:underline inline-flex items-center gap-1"
        >
          <User className="size-3.5" />
          {touch.client.name} ({touch.client.displayId})
        </Link>
        <div className="text-xs text-(--color-muted-foreground)">
          logged {fmt(touch.timestamp)}
          {touch.duration ? ` · ${touch.duration} min` : ""}
        </div>
      </Card>

      <Card className="p-5">
        <h2 className="font-semibold mb-3">Edit touch</h2>
        <ActionForm action={updateTouch}>
          <input type="hidden" name="id" value={touch.id} />
          <div className="space-y-3 text-sm">
            <div className="grid grid-cols-2 gap-2">
              <label className="block">
                <span className="text-[10px] uppercase tracking-wider font-semibold text-(--color-muted-foreground) block mb-1">
                  Kind
                </span>
                <select name="kind" defaultValue={touch.kind} className={INPUT_CLS}>
                  {KINDS.map((k) => (
                    <option key={k} value={k} className="capitalize">
                      {k.replace(/_/g, " ")}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-[10px] uppercase tracking-wider font-semibold text-(--color-muted-foreground) block mb-1">
                  Direction
                </span>
                <select
                  name="direction"
                  defaultValue={touch.direction ?? ""}
                  className={INPUT_CLS}
                >
                  {DIRECTIONS.map((d) => (
                    <option key={d} value={d}>
                      {d || "—"}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label className="block">
              <span className="text-[10px] uppercase tracking-wider font-semibold text-(--color-muted-foreground) block mb-1">
                Notes
              </span>
              <textarea
                name="notes"
                rows={4}
                defaultValue={touch.notes ?? ""}
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
