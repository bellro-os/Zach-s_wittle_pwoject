"use client";

import { useEffect, useState, useTransition } from "react";
import { toast } from "sonner";
import {
  Voicemail,
  PhoneOff,
  X as XIcon,
  FileText,
  DoorClosed,
} from "lucide-react";
import { logCallBulk, logDoorknockBulk } from "@/app/actions";
import { cn } from "@/lib/utils";

interface ParcelSelection {
  parcelId: string;
  county: string;
  owner: string;
  siteAddr: string;
}

function readSelected(): ParcelSelection[] {
  return Array.from(
    document.querySelectorAll<HTMLInputElement>("input.bulk-select:checked"),
  ).map((el) => ({
    parcelId: el.dataset.parcelId ?? "",
    county: el.dataset.county ?? "",
    owner: el.dataset.owner ?? "",
    siteAddr: el.dataset.addr ?? "",
  }));
}

const CALL_OUTCOMES: { value: string; label: string; Icon: typeof XIcon }[] = [
  { value: "left_voicemail", label: "Voicemail", Icon: Voicemail },
  { value: "no_answer", label: "No answer", Icon: PhoneOff },
  { value: "not_interested", label: "Not interested", Icon: XIcon },
];

const KNOCK_OUTCOMES: { value: string; label: string; Icon: typeof XIcon }[] = [
  { value: "left_flyer", label: "Left flyer", Icon: FileText },
  { value: "nobody_home", label: "Nobody home", Icon: DoorClosed },
  { value: "not_interested", label: "Not interested", Icon: XIcon },
];

export function BulkActionBar({ mode }: { mode: "call" | "knock" }) {
  const [count, setCount] = useState(0);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    function refresh() {
      setCount(readSelected().length);
    }
    refresh();
    document.addEventListener("change", refresh);
    return () => document.removeEventListener("change", refresh);
  }, []);

  if (count === 0) return null;

  const outcomes = mode === "knock" ? KNOCK_OUTCOMES : CALL_OUTCOMES;
  const action = mode === "knock" ? logDoorknockBulk : logCallBulk;

  function clearAll() {
    document
      .querySelectorAll<HTMLInputElement>("input.bulk-select:checked")
      .forEach((el) => (el.checked = false));
    setCount(0);
  }

  function submit(outcome: string) {
    const parcels = readSelected();
    if (!parcels.length) return;
    startTransition(async () => {
      const result = await action({ outcome, parcels });
      if (result.success) {
        toast.success(result.message ?? `Logged ${parcels.length}`);
        clearAll();
      } else {
        toast.error(result.error ?? "Bulk action failed");
      }
    });
  }

  return (
    <div
      className={cn(
        "sticky top-14 z-20 flex items-center gap-3 px-4 py-3 bg-(--color-primary) text-(--color-primary-foreground) rounded-lg shadow-md no-print",
        isPending && "opacity-70 pointer-events-none",
      )}
    >
      <span className="font-semibold text-sm">
        {count} selected
      </span>
      <span className="text-(--color-muted-foreground)">·</span>
      {outcomes.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => submit(o.value)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-(--color-background) text-(--color-foreground) text-xs font-medium hover:opacity-90"
        >
          <o.Icon className="size-3.5" />
          {o.label}
        </button>
      ))}
      <button
        type="button"
        onClick={clearAll}
        className="ml-auto text-xs underline opacity-80 hover:opacity-100"
      >
        Clear
      </button>
    </div>
  );
}
